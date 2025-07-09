# app.py

import os
import requests
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="gpt-docs-proxy-fallback",
    version="1.0",
    description="Fallback proxy: forwards /search to docs/search_content"
)

class SearchRequest(BaseModel):
    student: str
    query: str
    n: int = 5

class SearchResult(BaseModel):
    text: str
    score: float

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/search", response_model=List[SearchResult])
def search(req: SearchRequest):
    """
    Proxy `/search` to the existing /docs/search_content endpoint.
    """
    url = "https://gpt-docs-proxy.onrender.com/docs/search_content"
    params = {"student": req.student, "query": req.query, "n": req.n}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
    except requests.HTTPError:
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Student not found")
        raise HTTPException(status_code=502, detail="Upstream error")
    except Exception:
        raise HTTPException(status_code=502, detail="Upstream error")

    upstream = r.json()
    results: List[SearchResult] = []
    for item in upstream:
        text = "\n\n".join(item.get("lessons", []))
        results.append(SearchResult(text=text, score=0.0))
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
