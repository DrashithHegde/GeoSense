from pathlib import Path
path = Path("server/app/api/routes.py")
content = path.read_text(encoding="utf-8")
content = content.replace("SERVER_ROOT = Path(__file__).resolve().parents[3]", "SERVER_ROOT = Path(__file__).resolve().parents[2]")
path.write_text(content, encoding="utf-8")
