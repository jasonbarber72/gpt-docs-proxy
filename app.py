import os
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
import tiktoken

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secret-key")

# Google service account and scopes
SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]

# Token encoder
ENCODER = tiktoken.get_encoding("cl100k_base")

# Regex to identify date headings like "Fri 4 July 25"
DATE_HEADING_RE = re.compile(r"^[A-Za-z]{3,9} \d{1,2} [A-Za-z]{3,9} \d{2}$")

# Global API clients (initialized once)
DRIVE = None
DOCS  = None

def get_credentials():
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

@app.before_first_request
def init_clients():
    global DRIVE, DOCS
    creds = get_credentials()
    DRIVE = build("drive", "v3", credentials=creds)
    DOCS  = build("docs",  "v1", credentials=creds)

def extract_text(doc):
    """Extract all textRuns from a Docs API document response."""
    text = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for run in element["paragraph"]["elements"]:
                if "textRun" in run and run["textRun"].get("content"):
                    text += run["textRun"]["content"]
    return text

def parse_lessons(text_block):
    """
    Split a block of text into dated lessons.
    Discard any lines before the first date heading.
    Returns a list of lessons, each starting with a date heading.
    """
    lessons = []
    current = None
    for line in text_block.splitlines():
        line = line.rstrip()
        if DATE_HEADING_RE.match(line):
            if current:
                lessons.append("\n".join(current).strip())
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        lessons.append("\n".join(current).strip())
    return lessons

@app.route("/docs")
def search_docs_by_title():
    title = request.args.get("title", "").strip()
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
    doc  = DOCS.documents().get(documentId=doc_id).execute()
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
    data    = request.get_json() or {}
    doc_ids = data.get("doc_ids", [])
    results = []
    max_chunk = 10

    for i in range(0, len(doc_ids), max_chunk):
        chunk = doc_ids[i:i + max_chunk]
        for did in chunk:
            file = DRIVE.files().get(fileId=did, fields="name").execute()
            name = file.get("name")
            doc  = DOCS.documents().get(documentId=did).execute()
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
    doc   = DOCS.documents().get(documentId=doc_id).execute()
    paras = doc.get("body", {}).get("content", [])[start:end]
    text  = "".join(
        run["textRun"]["content"]
        for p in paras if "paragraph" in p
        for run in p["paragraph"].get("elements", [])
        if "textRun" in run
    )
    return jsonify({
        "id": doc_id,
        "name": doc.get("title", ""),
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
        did  = f["id"]
        name = f["name"]
        doc  = DOCS.documents().get(documentId=did).execute()
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
    """
    Query parameters:
      - n        (int, default=3): number of lessons per doc
      - weekday  (optional): filter by weekday in document name
      - student  (optional): comma-delimited list of student name fragments
    """
    n        = int(request.args.get("n", 3))
    weekday  = request.args.get("weekday", "").strip()
    students = [
        s.strip() for s in request.args.get("student", "").split(",")
        if s.strip()
    ]

    resp = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document' and name contains ' - Violin Practice'",
        fields="files(id,name)"
    ).execute()
    files = resp.get("files", [])

    if weekday:
        files = [f for f in files if weekday in f["name"]]
    if students:
        files = [f for f in files if any(st in f["name"] for st in students)]

    results = []
    for f in files:
        did, name = f["id"], f["name"]
        lessons, start_par = [], 0
        error = None

        try:
            while len(lessons) < n:
                doc   = DOCS.documents().get(documentId=did).execute()
                paras = doc.get("body", {}).get("content", [])[start_par:start_par+50]
                block = "".join(
                    run["textRun"]["content"]
                    for p in paras if "paragraph" in p
                    for run in p["paragraph"].get("elements", [])
                    if "textRun" in run
                )
                for lesson in parse_lessons(block):
                    if len(lessons) < n:
                        lessons.append(lesson)
                if len(paras) < 50:
                    break
                start_par += 50
        except Exception as e:
            error = str(e)

        results.append({
            "id": did,
            "name": name,
            "lessons": lessons[:n],
            "token_counts": [len(ENCODER.encode(l)) for l in lessons[:n]],
            "error": error
        })

    return jsonify(results)

@app.route("/docs/lessons_in_range")
def get_lessons_in_range():
    """
    Query parameters:
      - start_date (YYYY-MM-DD)
      - end_date   (YYYY-MM-DD)
      - weekday    (optional)
      - student    (optional, comma-delimited)
    """
    start = datetime.fromisoformat(request.args["start_date"])
    end   = datetime.fromisoformat(request.args["end_date"])
    weekday  = request.args.get("weekday", "").strip()
    students = [
        s.strip() for s in request.args.get("student", "").split(",")
        if s.strip()
    ]

    resp = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document' and name contains ' - Violin Practice'",
        fields="files(id,name)"
    ).execute()
    files = resp.get("files", [])

    if weekday:
        files = [f for f in files if weekday in f["name"]]
    if students:
        files = [f for f in files if any(st in f["name"] for st in students)]

    results = []
    for f in files:
        did, name = f["id"], f["name"]
        lessons, start_par = [], 0
        error = None

        try:
            while True:
                doc   = DOCS.documents().get(documentId=did).execute()
                paras = doc.get("body", {}).get("content", [])[start_par:start_par+50]
                block = "".join(
                    run["textRun"]["content"]
                    for p in paras if "paragraph" in p
                    for run in p["paragraph"].get("elements", [])
                    if "textRun" in run
                )
                for lesson in parse_lessons(block):
                    heading = lesson.splitlines()[0]
                    try:
                        dt = datetime.strptime(heading, "%a %d %b %y")
                        if start <= dt <= end:
                            lessons.append(lesson)
                    except ValueError:
                        continue
                if len(paras) < 50:
                    break
                start_par += 50
        except Exception as e:
            error = str(e)

        results.append({
            "id": did,
            "name": name,
            "lessons": lessons,
            "token_counts": [len(ENCODER.encode(l)) for l in lessons],
            "error": error
        })

    return jsonify(results)

@app.route("/docs/search_content")
def search_content():
    """
    Query parameters:
      - query   (string, required)
      - n       (int, default=5)
      - student (optional, comma-delimited)
    """
    q        = request.args.get("query", "").strip()
    n        = int(request.args.get("n", 5))
    students = [
        s.strip() for s in request.args.get("student", "").split(",")
        if s.strip()
    ]

    resp = DRIVE.files().list(
        q=(
            f"fullText contains '{q}' "
            "and mimeType='application/vnd.google-apps.document' "
            "and name contains ' - Violin Practice'"
        ),
        pageSize=n,
        fields="files(id,name)"
    ).execute()
    files = resp.get("files", [])
    if students:
        files = [f for f in files if any(st in f["name"] for st in students)]

    results = []
    for f in files:
        did, name = f["id"], f["name"]
        error = None
        lessons = []
        try:
            doc = DOCS.documents().get(documentId=did).execute()
            text = extract_text(doc)
            for lesson in parse_lessons(text):
                if q.lower() in lesson.lower():
                    lessons.append(lesson)
                    if len(lessons) >= n:
                        break
        except Exception as e:
            error = str(e)

        results.append({
            "id": did,
            "name": name,
            "lessons": lessons,
            "token_counts": [len(ENCODER.encode(l)) for l in lessons],
            "error": error
        })

    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
