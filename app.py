# app.py

import os
import json
import requests
from functools import lru_cache
from typing import List
import faiss
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from openai.embeddings_utils import get_embedding

# ─── Configuration ────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Environment variable OPENAI_API_KEY is required")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(
    title="gpt-docs-proxy",
    version="1.0",
    description="Search student violin lesson notes via embeddings + FAISS"
)

# ─── Request / Response Models ─────────────────────────────────────────────────
class SearchRequest(BaseModel):
    student: str
    query: str
    n: int = 5

class SearchResult(BaseModel):
    text: str
    score: float

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

# ─── Search Endpoint ──────────────────────────────────────────────────────────
@app.post("/search", response_model=List[SearchResult])
async def search(req: SearchRequest):
    try:
        index, docs = _get_vector_index(req.student)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    query_emb = get_embedding(
        req.query,
        engine="text-embedding-ada-002",
        api_key=OPENAI_API_KEY
    )
    qv = np.array(query_emb, dtype="float32").reshape(1, -1)

    D, I = index.search(qv, req.n)
    results = []
    for dist, idx in zip(D[0], I[0]):
        if 0 <= idx < len(docs):
            results.append(SearchResult(text=docs[idx], score=float(dist)))
    return results

# ─── Caching & Index Building ─────────────────────────────────────────────────
@lru_cache(maxsize=10)
def _get_vector_index(student: str):
    file_id = _student_to_file_id(student)
    idx_url = f"https://gpt-docs-proxy.onrender.com/docs/index/read?file_id={file_id}"
    r = requests.get(idx_url, timeout=10)
    r.raise_for_status()
    index_json = r.json()
    docs = [chunk["text"] for chunk in index_json]

    embs = [get_embedding(text, engine="text-embedding-ada-002", api_key=OPENAI_API_KEY)
            for text in docs]
    embs = np.array(embs, dtype="float32")

    dim = embs.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embs)
    return index, docs

def _student_to_file_id(student: str) -> str:
    mapping = {
        "Charlotte": "1usQGAus2F361i8IcNDy9FVdCV4t-ePtb",
        "Leo":        "1bcdEFghIjklMnopQRsTuvWXyZ123456"
    }
    if student not in mapping:
        raise KeyError(f"No index file configured for student '{student}'")
    return mapping[student]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
