# Filename: app.py

import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, List, Dict

# ─── App Initialization ───────────────────────────────────────────────────────
app = FastAPI(
    title="gpt-docs-proxy",
    version="1.0",
    description="Proxy for fetching and searching Google Docs–based lesson notes"
)

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

# ─── Search Endpoint (proxy to /docs/search_content) ─────────────────────────
class SearchRequest(BaseModel):
    student: str
    query: str
    n: int = 5

@app.post("/search")
async def search(req: SearchRequest) -> List[Dict[str, Any]]:
    """
    Proxy semantic searches to the remote /docs/search_content endpoint.
    Returns whatever that endpoint returns (an array of lesson objects).
    """
    url = "https://gpt-docs-proxy.onrender.com/docs/search_content"
    try:
        resp = requests.get(
            url,
            params={"student": req.student, "query": req.query, "n": req.n},
            timeout=10
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Docs service error: {e}")
    return resp.json()
