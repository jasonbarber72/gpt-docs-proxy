import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
import tiktoken

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secret-key")

SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]

ENCODER = tiktoken.get_encoding("cl100k_base")

def get_credentials():
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

def extract_text(doc):
    text = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                if "textRun" in run and run["textRun"].get("content"):
                    text += run["textRun"]["content"]
    return text

@app.route("/docs")
def search_docs_by_title():
    title = request.args.get("title", "")
    if not title:
        return jsonify([]), 400
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    query = f"name contains '{title}' and mimeType='application/vnd.google-apps.document'"
    response = drive.files().list(q=query, fields="files(id,name)").execute()
    return jsonify(response.get("files", []))

@app.route("/docs/all")
def list_all_docs():
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    response = drive.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    return jsonify(response.get("files", []))

@app.route("/docs/<doc_id>")
def read_doc_by_id(doc_id):
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    file = drive.files().get(fileId=doc_id, fields="name").execute()
    name = file.get("name")
    doc = docs_service.documents().get(documentId=doc_id).execute()
    text = extract_text(doc)
    char_count = len(text)
    token_count = len(ENCODER.encode(text))
    return jsonify({
        "id": doc_id,
        "name": name,
        "text": text,
        "char_count": char_count,
        "token_count": token_count
    })

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    """
    Read multiple docs; automatically splits into chunks of 3 to avoid payload-too-large.
    """
    data = request.get_json() or {}
    doc_ids = data.get("doc_ids", [])
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)

    results = []
    max_chunk_size = 3  # change if you need smaller/larger chunks

    # Process in chunks
    for i in range(0, len(doc_ids), max_chunk_size):
        chunk = doc_ids[i : i + max_chunk_size]
        for doc_id in chunk:
            file = drive.files().get(fileId=doc_id, fields="name").execute()
            name = file.get("name")
            doc = docs_service.documents().get(documentId=doc_id).execute()
            text = extract_text(doc)
            char_count = len(text)
            token_count = len(ENCODER.encode(text))
            results.append({
                "id": doc_id,
                "name": name,
                "text": text,
                "char_count": char_count,
                "token_count": token_count
            })

    return jsonify(results)

@app.route("/docs/<doc_id>/page")
def read_doc_page(doc_id):
    start = int(request.args.get("start_par", 0))
    end   = int(request.args.get("end_par", start + 50))
    creds = get_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    doc = docs_service.documents().get(documentId=doc_id).execute()
    paras = doc.get("body", {}).get("content", [])[start:end]
    text = "".join(
        run["textRun"]["content"]
        for p in paras if "paragraph" in p
        for run in p["paragraph"].get("elements", [])
        if "textRun" in run
    )
    char_count  = len(text)
    token_count = len(ENCODER.encode(text))
    return jsonify({
        "id": doc_id,
        "name": doc.get("title", ""),
        "text": text,
        "char_count": char_count,
        "token_count": token_count,
        "next_start": end
    })

@app.route("/docs/metadata")
def list_docs_metadata():
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)

    response = drive.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    files = response.get("files", [])

    metadata = []
    for f in files:
        doc_id    = f.get("id")
        file_name = f.get("name")
        doc       = docs_service.documents().get(documentId=doc_id).execute()
        text      = extract_text(doc)
        metadata.append({
            "id": doc_id,
            "name": file_name,
            "char_count": len(text),
            "token_count": len(ENCODER.encode(text))
        })

    return jsonify(metadata)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
