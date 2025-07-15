import os
import json
import requests
from openai import OpenAI
import numpy as np
import faiss

# Configuration
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
DOCS_SERVICE_URL = os.getenv('DOCS_SERVICE_URL', 'http://127.0.0.1:8001')

# 1. Fetch all documents
all_docs = requests.get(f"{DOCS_SERVICE_URL}/docs/all").json()

ids = []
texts = []
for doc in all_docs:
    ids.append(doc['id'])
    read = requests.get(f"{DOCS_SERVICE_URL}/docs/read?file_id={doc['id']}").json()
    texts.append(read['text'])

# 2. Compute embeddings
embs = []
for txt in texts:
    resp = client.embeddings.create(model='text-embedding-ada-002', input=txt)
    embs.append(np.array(resp['data'][0]['embedding'], dtype='float32'))

# 3. Build FAISS index
dim = embs[0].shape[0]
index = faiss.IndexFlatL2(dim)
index.add(np.stack(embs))

# 4. Persist index and IDs
faiss.write_index(index, 'index.faiss')
with open('ids.json', 'w') as f:
    json.dump(ids, f)

print(f'Index built for {len(ids)} documents (dim={dim})')
