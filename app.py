# app.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import requests
from functools import lru_cache

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores.faiss import FAISS

app = FastAPI()

# Allow all CORS (needed for ChatGPT plugin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache()
def build_or_load_charlotte_index():
    """
    Fetches the raw index JSON for Charlotte,
    splits into chunks, embeds with OpenAI,
    and builds a local FAISS index. Cached on first call.
    """
    resp = requests.get(
        "https://gpt-docs-proxy.onrender.com/docs/index/read"
        "?file_id=1usQGAus2F361i8IcNDy9FVdCV4t-ePtb"
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch index: {resp.status_code}")
    items = resp.json()
    texts = [item["text"] for item in items]

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = splitter.create_documents(texts)

    embeddings = OpenAIEmbeddings()
    vector_store = FAISS.from_documents(docs, embeddings)
    return vector_store


class SearchResponse(BaseModel):
    text: str
    score: float


@app.get("/docs/search_content", response_model=List[SearchResponse])
def search_content(
    student: str = Query(..., description="Student name, e.g. Charlotte"),
    query: str = Query(..., description="Search query"),
    n: int = Query(5, description="Number of results"),
):
    """
    Search the FAISS index for the given student.
    Currently only 'Charlotte' is supported.
    """
    if student.lower() == "charlotte":
        index = build_or_load_charlotte_index()
    else:
        raise HTTPException(404, f"No index for student '{student}'")

    results = index.similarity_search_with_score(query, k=n)
    return [
        SearchResponse(text=doc.page_content, score=score)
        for doc, score in results
    ]


@app.on_event("startup")
def on_startup():
    # Pre-load Charlotte’s index so the first request is fast
    build_or_load_charlotte_index()


# Optional: local test runner
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
