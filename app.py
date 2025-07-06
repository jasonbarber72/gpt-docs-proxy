import os
import re
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
DATE_HEADING_RE = re.compile(r"^[A-Za-z]{3,9} \d{1,2} [A-Za-z]{3,9} \d{2}$")

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

def parse_lessons(text_block):
    lines = text_block.splitlines()
    lessons = []
    current = None
    for line in lines:
        line = line.strip()
        if DATE_HEADING_RE.match(line):
            if current:
                lessons.append("\n".join(current).strip())
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        lessons.append("\n".join(current).strip())
    return lessons

@app.before_first_request
def init_clients():
    global DRIVE, DOCS
    creds = get_credentials()
    DRIVE = build("drive", "v3", credentials=creds)
    DOCS  = build("docs", "v1", credentials=creds)

@app.route("/docs")
def search_docs_by_title():
    title = request.args.get("title", "")
    if not title:
        return jsonify([]), 400
    resp = DRIVE.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    return jsonify(resp.get("files", []))

@app.route("/docs/all")
def list_all_docs():
    resp = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    return jsonify(resp.get("files", []))

@app.route("/docs/<doc_id>")
def read_doc_by_id(doc_id):
    file = DRIVE.files().get(fileId=doc_id, fields="name").execute()
    name = file.get("name")
    doc = DOCS.documents().get(documentId=doc_id).execute()
    text = extract_text(doc)
    return jsonify({
        "id": doc_id,
        "name": name,
        "text": text,
        "char_count": len(text),
        "token_count": len(ENCODER.encode(text))
    })

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    data = request.get_json() or {}
    doc_ids = data.get("doc_ids", [])
    results = []
    max_chunk = 10
    for i in range(0, len(doc_ids), max_chunk):
        chunk = doc_ids[i:i+max_chunk]
        for did in chunk:
            file = DRIVE.files().get(fileId=did, fields="name").execute()
            name = file["name"]
            doc = DOCS.documents().get(documentId=did).execute()
            text = extract_text(doc)
            results.append({
                "id": did,
                "name": name,
                "text": text,
                "char_count": len(text),
                "token_count": len(ENCODER.encode(text))
            })
    return jsonify(results)

@app.route("/docs/<doc_id>/page")
def read_doc_page(doc_id):
    start = int(request.args.get("start_par", 0))
    end   = int(request.args.get("end_par", start + 50))
    doc = DOCS.documents().get(documentId=doc_id).execute()
    paras = doc.get("body", {}).get("content", [])[start:end]
    text = "".join(
        run["textRun"]["content"]
        for p in paras if "paragraph" in p
        for run in p["paragraph"].get("elements", [])
        if "textRun" in run
    )
    return jsonify({
        "id": doc_id,
        "name": doc.get("title",""),
        "text": text,
        "char_count": len(text),
        "token_count": len(ENCODER.encode(text)),
        "next_start": end
    })

@app.route("/docs/metadata")
def list_docs_metadata():
    resp = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document' and name contains ' - Violin Practice'",
        fields="files(id,name)"
    ).execute()
    files = resp.get("files", [])
    meta = []
    for f in files:
        did = f["id"]
        name = f["name"]
        doc = DOCS.documents().get(documentId=did).execute()
        text = extract_text(doc)
        meta.append({
            "id": did,
            "name": name,
            "char_count": len(text),
            "token_count": len(ENCODER.encode(text))
        })
    return jsonify(meta)

@app.route("/docs/last_lessons")
def get_last_lessons():
    n = int(request.args.get("n", 3))
    weekday = request.args.get("weekday", "").strip()
    resp = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document' and name contains ' - Violin Practice'",
        fields="files(id,name)"
    ).execute()
    files = resp.get("files", [])
    if weekday:
        files = [f for f in files if weekday in f["name"]]
    results = []
    for f in files:
        did, name = f["id"], f["name"]
        lessons, start = [], 0
        while len(lessons) < n:
            doc = DOCS.documents().get(documentId=did).execute()
            paras = doc.get("body", {}).get("content", [])[start:start+50]
            block = "".join(
                run["textRun"]["content"]
                for p in paras if "paragraph" in p
                for run in p["paragraph"].get("elements", [])
                if "textRun" in run
            )
            new = parse_lessons(block)
            for l in new:
                if len(lessons) < n:
                    lessons.append(l)
            if len(lessons)>=n or len(paras)<50:
                break
            start += 50
        results.append({
            "id": did,
            "name": name,
            "lessons": lessons[:n],
            "token_counts": [len(ENCODER.encode(l)) for l in lessons[:n]]
        })
    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
