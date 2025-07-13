import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DOCS_SERVICE_URL = os.getenv(
    "DOCS_SERVICE_URL",
    "https://gpt-docs-basic.onrender.com"
)

app = FastAPI(
    title="My Teaching (Basic) Proxy",
    version="0.1.0"
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/docs/all")
def list_all_docs():
    try:
        resp = requests.get(f"{DOCS_SERVICE_URL}/docs/all")
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Docs service error: {e}")

@app.get("/docs/read")
def read_doc(file_id: str):
    try:
        resp = requests.get(
            f"{DOCS_SERVICE_URL}/docs/read",
            params={"file_id": file_id}
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Docs service error: {e}")

class SearchRequest(BaseModel):
    student: str
    query: str
    n: int = 3

@app.post("/search")
def search_content(req: SearchRequest):
    try:
        # pointing at GET /docs/search_content on the basic service
        resp = requests.get(
            f"{DOCS_SERVICE_URL}/docs/search_content",
            params=req.dict()
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Docs service error: {e}")
