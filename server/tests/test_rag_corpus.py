"""RAG ingestion + vector store: PDF -> pages -> clean -> passages (with page numbers) -> embeddings ->
pgvector / in-memory -> hybrid retrieval with page citations.
Fixture PDFs are generated in a temporary folder; the pgvector check uses a temporary schema that is
dropped afterwards, so the real corpus, data folder and database tables are never touched."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

HEAT = ("Cool roofs with high solar reflectance lower roof surface temperatures and reduce the urban heat island. "
        "Reviews of reflective and green roof technologies report substantial reductions in peak surface temperature. ")
TREES = ("Tree canopy provides shade and evapotranspiration; parks and street trees are on average cooler than "
         "surrounding built-up areas during the day, and cooling increases with canopy cover. ")
REFS = "\n".join(f"Author{i}, A. ({2000 + i}). Some title. Journal {i}, 1-10. doi:10.1000/x{i}" for i in range(15))


def _pdf(path: Path, pages: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    for text in pages:
        y = 800
        for line in text.split("\n"):
            words, cur = line.split(), ""
            for w in words:
                if len(cur) + len(w) > 90:
                    c.drawString(40, y, cur)
                    y -= 14
                    cur = ""
                cur += w + " "
            c.drawString(40, y, cur)
            y -= 14
        c.showPage()
    c.save()


try:
    import reportlab  # noqa: F401  (only needed to build a test PDF)
    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False


@unittest.skipUnless(_HAS_REPORTLAB, "reportlab not installed (pip install reportlab)")
class CorpusPipelineTests(unittest.TestCase):
    def test_pages_cleaned_chunked_and_cited_by_page(self):
        from app.services.rag import corpus
        tmp = Path(tempfile.mkdtemp())
        _pdf(tmp / "doc.pdf", ["Contents\nIntroduction ........ 1\nMethods ........ 4", HEAT * 25, TREES * 6,
                               "References\n" + REFS])
        doc = {"id": "fixture", "type": "pdf", "title": "Fixture report", "citation": "Fixture (2024).",
               "source_type": "peer-reviewed", "urls": ["http://x"], "landing": "https://doi.org/10/x",
               "supports": ["mitigate_heat"]}
        pages = corpus.extract_pages(tmp / "doc.pdf", "pdf")
        self.assertEqual(len(pages), 4)
        ps = corpus.passages_for(doc, pages)
        self.assertTrue(ps)
        self.assertEqual({p["page"] for p in ps}, {2, 3})          # contents + reference pages dropped
        self.assertTrue(all(len(p["text"].split()) <= corpus.CHUNK_WORDS + 40 for p in ps))
        self.assertGreater(sum(1 for p in ps if p["page"] == 2), 1)  # long page -> several passages
        a, b = [p["text"].split() for p in ps if p["page"] == 2][:2]
        self.assertEqual(a[-corpus.OVERLAP_WORDS:], b[:corpus.OVERLAP_WORDS])   # overlap kept
        self.assertTrue(all(p["id"].startswith("fixture:p") for p in ps))

    def test_download_tries_mirrors_and_rejects_non_pdf(self):
        from app.services.rag import corpus
        tmp = Path(tempfile.mkdtemp())

        class R:
            def __init__(self, body):
                self.content = body

            def raise_for_status(self):
                pass

        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return R(b"<html>login</html>" if "bad" in url else b"%PDF-1.4 fake")

        doc = {"id": "d", "type": "pdf", "urls": ["http://bad/a.pdf", "http://good/b.pdf"]}
        with mock.patch("requests.get", fake_get):
            path, how = corpus.download(doc, raw_dir=tmp)
        self.assertEqual(how, "http://good/b.pdf")
        self.assertEqual(calls, ["http://bad/a.pdf", "http://good/b.pdf"])
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_every_listed_source_is_complete(self):
        from app.services.rag import corpus, retriever
        notes = {d["knowledge_id"] for d in retriever.load_kb()}
        for d in corpus.load_sources():
            self.assertTrue(d["citation"] and d["urls"] and d["title"], d["id"])
            self.assertTrue(set(d["supports"]) <= notes, d["id"])      # supports real notes only
            self.assertIn(d["source_type"], {"peer-reviewed", "government / official",
                                             "dataset / product documentation"})


class FakeEmbedder:
    name, dim, min_cos = "fake-bow", 64, 0.3

    def _v(self, t):
        v = np.zeros(self.dim, dtype="float32")
        for w in t.lower().split():
            v[hash(w.strip(".,;:")) % self.dim] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_docs(self, texts):
        return np.vstack([self._v(t) for t in texts])

    def embed_query(self, text):
        return self._v(text)


class VectorStoreTests(unittest.TestCase):
    def _items(self):
        return [{"id": "n1", "kind": "note", "title": "Heat", "text": HEAT, "citation": "c"},
                {"id": "d:p3:0", "kind": "passage", "doc_id": "d", "page": 3, "title": "Doc", "text": TREES,
                 "citation": "Doc (2020)"}]

    def test_memory_store_roundtrip(self):
        from app.services.rag import vector_store as vs
        tmp = Path(tempfile.mkdtemp())
        e = FakeEmbedder()
        with mock.patch.object(vs, "VECTORS", tmp / "v.npy"), mock.patch.object(vs, "VECTOR_IDS", tmp / "i.json"), \
                mock.patch.object(vs, "META", tmp / "m.json"):
            items = self._items()
            vs.MemoryStore.save(items, e.embed_docs([i["text"] for i in items]), {"embedder": e.name, "items": 2})
            got = vs.MemoryStore().search(e.embed_query("street trees canopy shade"), k=2)
        self.assertEqual(next(iter(got)), "d:p3:0")

    def test_pgvector_hnsw_search(self):
        from sqlalchemy import create_engine, text

        from app.database import engine
        from app.services.rag import vector_store as vs
        try:
            if not vs.PgVectorStore.try_enable(engine):
                self.skipTest("pgvector not available in this database")
        except Exception as exc:
            self.skipTest(f"database not available: {exc}")
        schema = "rag_test_tmp"
        with engine.connect() as c:   # the real store (if any) must be untouched by this test
            real = c.execute(text("SELECT to_regclass('public.rag_items')")).scalar()
            before = c.execute(text("SELECT count(*) FROM public.rag_items")).scalar() if real else None
        with engine.begin() as c:
            c.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            c.execute(text(f"CREATE SCHEMA {schema}"))
        eng = create_engine(engine.url, connect_args={"options": f"-csearch_path={schema},public"})
        try:
            e = FakeEmbedder()
            st = vs.PgVectorStore(eng)
            st.ensure_schema(e.dim)
            items = self._items()
            n = st.replace_all(items, e.embed_docs([i["text"] for i in items]), {"embedder": e.name, "items": 2})
            self.assertEqual(n, 2)
            got = st.search(e.embed_query("cool roofs reflective heat island"), k=2)
            self.assertEqual(next(iter(got)), "n1")
            self.assertEqual(st.meta()["embedder"], e.name)
            with eng.connect() as c:
                idx = c.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'rag_items_hnsw'")).scalar()
            self.assertIn("hnsw", idx)
            st.ensure_schema(e.dim + 1)          # a different embedding size rebuilds the table
            with eng.connect() as c:
                self.assertEqual(c.execute(text("SELECT count(*) FROM rag_items")).scalar(), 0)
        finally:
            eng.dispose()
            with engine.begin() as c:
                c.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            with engine.connect() as c:
                still = c.execute(text("SELECT to_regclass('public.rag_items')")).scalar()
                after = c.execute(text("SELECT count(*) FROM public.rag_items")).scalar() if still else None
            self.assertEqual((bool(real), before), (bool(still), after))


class RetrieverRobustnessTests(unittest.TestCase):
    def test_a_broken_vector_store_never_breaks_retrieval(self):
        from app.services.rag import retriever

        class Broken:
            kind = "broken"

            def search(self, q, k):
                raise RuntimeError("relation rag_items does not exist")

        if not retriever.embeddings_available():
            self.skipTest("no embedding model")
        retriever._store.cache_clear()
        with mock.patch.object(retriever, "_store", lambda: Broken()):
            got = retriever.retrieve("urban heat island built-up surface temperature", k=3)
        self.assertTrue(got)


class RetrieverWithCorpusTests(unittest.TestCase):
    def test_passages_cited_with_page_and_capped_per_document(self):
        from app.services.rag import retriever
        notes = list(retriever.load_kb())
        passages = [{"id": f"big:p{i}:0", "doc_id": "big", "kind": "passage", "page": i, "title": "Big report",
                     "citation": "Big (2022).", "url": "https://doi.org/x", "source_type": "government / official",
                     "supports": ["mitigate_heat"], "text": HEAT * 3} for i in range(1, 8)]
        items = tuple(notes + [retriever._passage_item(p) for p in passages])
        for f in (retriever.load_items, retriever._index, retriever._by_id):
            f.cache_clear()
        with mock.patch.object(retriever, "load_items", lambda: items), \
                mock.patch.object(retriever, "embeddings_available", lambda: False):
            retriever._index.cache_clear()
            retriever._by_id.cache_clear()
            got = retriever.retrieve("cool roofs reflective heat island", k=6)
            self.assertLessEqual(sum(1 for d in got if d.get("doc_id") == "big"), retriever.MAX_PER_DOC)
            p = next(d for d in got if d["kind"] == "passage")
            self.assertRegex(p["title"], r", p\. \d+$")
            self.assertTrue(p["source"].endswith(f"p. {p['page']}"))
            only_notes = retriever.retrieve("cool roofs reflective heat island", k=6, include_passages=False)
            self.assertTrue(all(d["kind"] == "note" for d in only_notes))
        retriever._index.cache_clear()
        retriever._by_id.cache_clear()


class PlaceNameTests(unittest.TestCase):
    V6 = {"features": [
        {"properties": {"feature_type": "place", "name": "Mumbai", "context": {}}},
        {"properties": {"feature_type": "neighborhood", "name": "Powai",
                        "context": {"locality": {"name": "Andheri East"}, "place": {"name": "Mumbai"}}}}]}

    def test_neighbourhood_preferred_and_municipality_from_our_boundaries(self):
        from app.services import place_names as pn
        p = pn.parse_v6(self.V6)
        self.assertEqual((p["name"], p["city"]), ("Powai", "Mumbai"))
        self.assertEqual(pn.label(p, "Mumbai"), "Powai, Mumbai")
        self.assertEqual(pn.label({"name": "Thane", "city": "Thane"}, "Thane"), "Thane")    # no "Thane, Thane"
        self.assertEqual(pn.label(None, "Mira-Bhayandar"), "Mira-Bhayandar")

    def test_v5_fallback_and_offline_behaviour(self):
        from app.services import place_names as pn
        v5 = {"features": [{"place_type": ["locality"], "text": "Wagle Estate",
                            "context": [{"id": "place.123", "text": "Thane"}]}]}
        self.assertEqual(pn.parse_v5(v5)["name"], "Wagle Estate")
        pn._CACHE.clear()
        with mock.patch.object(pn, "_token", lambda: None):
            out = pn.place_name(72.97, 19.20, "Thane")
        self.assertEqual(out["label"], "Thane")                  # no token/internet: municipality, never coordinates
        self.assertIn("boundaries", out["source"])


class FactorEvidenceTests(unittest.TestCase):
    def test_factor_gets_document_page_or_falls_back_to_note(self):
        from app.services.rag import explainer as E
        f = {"theme": "heat", "kb": "uhi", "text": "A high built-up share is consistent with the surface urban heat island."}
        page = {"knowledge_id": "doc:p4:0", "kind": "passage", "title": "Report, p. 4", "source": "Report (2020), p. 4",
                "url": "https://doi.org/x", "content": "Impervious surfaces raise surface temperature " * 20}
        with mock.patch.object(E.retriever, "retrieve", lambda *a, **k: [page]):
            ev = E._factor_evidence(f, "Mumbai")
        self.assertEqual(ev["kind"], "passage")
        self.assertTrue(ev["title"].endswith("p. 4"))
        with mock.patch.object(E.retriever, "retrieve", lambda *a, **k: []):
            ev = E._factor_evidence(f, "Mumbai")
        self.assertEqual(ev["kind"], "note")
        self.assertIn("Oke", ev["source"])


if __name__ == "__main__":
    unittest.main()
