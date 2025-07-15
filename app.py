from dotenv import load_dotenv
load_dotenv()

import os
import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="gpt-docs-proxy", version="0.1.0")
DOCS_SERVICE_URL = os.getenv("DOCS_SERVICE_URL")

class SearchRequest(BaseModel):
    student: str
    query: str
    n: int = 5

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
def read_doc(file_id: str = Query(..., alias="file_id")):
    try:
        resp = requests.get(f"{DOCS_SERVICE_URL}/docs/read", params={"file_id": file_id})
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Docs service error: {e}")

@app.post("/search")
def search(req: SearchRequest):
    try:
        # Forward as POST to the Basic service's /search endpoint
        resp = requests.post(
            f"{DOCS_SERVICE_URL}/search",
            json=req.dict(),
            headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Search proxy error: {e}")
