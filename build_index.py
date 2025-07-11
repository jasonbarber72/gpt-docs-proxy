import os, json
import numpy as np
from openai.embeddings_utils import get_embedding
import faiss
from sklearn.decomposition import PCA

API_KEY = os.getenv("OPENAI_API_KEY")

def build_index(documents):
    # documents: list of {"id": ..., "name": ..., "text": ...}
    embeddings = [get_embedding(d["text"]) for d in documents]
    dim = len(embeddings[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings, dtype="float32"))
    return index

if __name__ == "__main__":
    # Load all docs, call build_index, save index to file
    from app import list_all_docs, read_doc
    docs_meta = list_all_docs()
    docs = [read_doc(file_id=d["id"]) for d in docs_meta]
    idx = build_index(docs)
    with open("index.faiss", "wb") as f:
        f.write(idx.serialize())
    print("Index built and saved to index.faiss")
