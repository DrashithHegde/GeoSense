# GeoSense API - production image (Render, Azure App Service, any container host).
# Local development uses docker-compose.yml, which mounts the code and adds --reload.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RAG_EMBEDDER=auto \
    WARM_UP=1

WORKDIR /app

# rasterio, shapely and psycopg2 come as self-contained wheels; libexpat is the one system library
# the rasterio wheel expects on slim images
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# the RAG embedding model (BAAI/bge-small-en-v1.5, ONNX) is baked into the image so the server
# never downloads it at run time; if the build has no internet, retrieval falls back to BM25
RUN python -c "from app.services.rag.embedder import BgeEmbedder; BgeEmbedder(allow_download=True); print('bge-small ready')" \
    || echo "WARNING: embedding model not downloaded - RAG will use BM25 only"

RUN chmod +x deploy/start.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('PORT','8000'), timeout=4)" || exit 1
CMD ["sh", "deploy/start.sh"]
