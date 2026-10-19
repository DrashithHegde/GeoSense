import time
import requests

start = time.time()
try:
    resp = requests.get("http://127.0.0.1:8000/api/zones/1/explanation")
    print(f"Status: {resp.status_code}")
    print(f"Time: {time.time() - start:.3f}s")
except Exception as e:
    print(e)
