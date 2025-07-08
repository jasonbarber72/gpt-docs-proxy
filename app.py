import os
import re
import io
import json
import difflib
from datetime import datetime
from collections import Counter

from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import tiktoken

# ---- Flask & CORS setup ----
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secret-key")

# ---- Google API setup ----
SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]
DRIVE = None
DOCS  = None

def get_credentials():
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

@app.before_first_request
def init_clients():
    global DRIVE, DOCS
    creds = get_credentials()
    DRIVE = build("drive", "v3", credentials=creds)
    DOCS  = build("docs", "v1", credentials=creds)

# ---- Text encoding & parsing ----
ENCODER = tiktoken.get_encoding("cl100k_base")
DATE_HEADING_RE = re.compile(r"^[A-Za-z]{3,9} \d{1,2} [A-Za-z]{3,9} \d{2}$")

def extract_text(doc_json):
    text = ""
    for el in doc_json.get("body", {}).get("content", []):
        if "paragraph" in el:
            for run in el["paragraph"]["elements"]:
                if "textRun" in run and run["textRun"].get("content"):
                    text += run["textRun"]["content"]
    return text

def parse_lessons(text_block):
    lessons, current = [], None
    for line in text_block.splitlines():
        if DATE_HEADING_RE.match(line):
            if current:
                lessons.append("\n".join(current).strip())
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        lessons.append("\n".join(current).strip())
    return lessons

def filter_by_students(files, student_queries):
    """Fuzzy-match each query against file['name']."""
    if not student_queries:
        return files
    names = [f["name"] for f in files]
    matched = set()
    for query in student_queries:
        # direct substring
        for f in files:
            if query.lower() in f["name"].lower():
                matched.add(f["id"])
        # fuzzy matches
        for name in difflib.get_close_matches(query, names, cutoff=0.6):
            for f in files:
                if f["name"] == name:
                    matched.add(f["id"])
    return [f for f in files if f["id"] in matched]

def compute_memory_usage(docs_meta):
    total_words = sum(round(m["token_count"] * 0.75) for m in docs_meta)
    percent = round(total_words / 32000 * 100)
    return total_words, percent

# ---- Common file listing ----
def list_all_docs_raw():
    return DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute().get("files", [])

# ---- Endpoints ----

@app.route("/docs")
def search_docs_by_title():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"error": "Missing title"}), 400
    resp = DRIVE.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    return jsonify(resp.get("files", []))

@app.route("/docs/all")
def list_all_docs():
    files = list_all_docs_raw()
    return jsonify(files)

@app.route("/docs/<doc_id>")
def read_doc_by_id(doc_id):
    try:
        file_meta = DRIVE.files().get(fileId=doc_id, fields="name").execute()
        doc_json   = DOCS.documents().get(documentId=doc_id).execute()
        text       = extract_text(doc_json)
        tokens     = len(ENCODER.encode(text))
        return jsonify({
            "id": doc_id,
            "name": file_meta["name"],
            "text": text,
            "char_count": len(text),
            "token_count": tokens
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    ids = (request.get_json() or {}).get("doc_ids", [])
    out = []
    for did in ids:
        resp = read_doc_by_id(did)
        if resp.status_code == 200:
            out.append(resp.get_json())
    return jsonify(out)

@app.route("/docs/<doc_id>/page")
def read_doc_page(doc_id):
    try:
        s = int(request.args.get("start_par", 0))
        e = int(request.args.get("end_par", s + 50))
        doc_json = DOCS.documents().get(documentId=doc_id).execute()
        paras = doc_json["body"]["content"][s:e]
        text = "".join(
            run["textRun"]["content"]
            for p in paras if "paragraph" in p
            for run in p["paragraph"]["elements"]
            if "textRun" in run
        )
        tokens = len(ENCODER.encode(text))
        return jsonify({
            "id": doc_id,
            "text": text,
            "char_count": len(text),
            "token_count": tokens,
            "next_start": e
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/docs/metadata")
def list_docs_metadata():
    files = list_all_docs_raw()
    meta = []
    for f in files:
        doc_json = DOCS.documents().get(documentId=f["id"]).execute()
        txt = extract_text(doc_json)
        meta.append({
            "id": f["id"],
            "name": f["name"],
            "char_count": len(txt),
            "token_count": len(ENCODER.encode(txt))
        })
    return jsonify(meta)

@app.route("/docs/last_lessons")
def get_last_lessons():
    try:
        n  = int(request.args.get("n", 3))
        wd = request.args.get("weekday", "").strip()
        st = [s.strip() for s in request.args.get("student", "").split(",") if s.strip()]

        files = list_all_docs_raw()
        if wd:
            files = [f for f in files if wd.lower() in f["name"].lower()]
        files = filter_by_students(files, st)

        result = []
        for f in files:
            lessons = []
            sp = 0
            while len(lessons) < n:
                doc_json = DOCS.documents().get(documentId=f["id"]).execute()
                block = extract_text(doc_json)
                for L in parse_lessons(block):
                    lessons.append(L)
                    if len(lessons) >= n:
                        break
                break
            result.append({
                "id": f["id"],
                "name": f["name"],
                "lessons": lessons[:n],
                "token_counts": [len(ENCODER.encode(L)) for L in lessons[:n]]
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/docs/lessons_in_range")
def get_lessons_in_range():
    try:
        sd = datetime.fromisoformat(request.args["start_date"])
        ed = datetime.fromisoformat(request.args["end_date"])
        wd = request.args.get("weekday", "").strip()
        st = [s.strip() for s in request.args.get("student", "").split(",") if s.strip()]

        files = list_all_docs_raw()
        if wd:
            files = [f for f in files if wd.lower() in f["name"].lower()]
        files = filter_by_students(files, st)

        result = []
        for f in files:
            lessons = []
            doc_json = DOCS.documents().get(documentId=f["id"]).execute()
            for L in parse_lessons(extract_text(doc_json)):
                hd = L.splitlines()[0]
                try:
                    dt = datetime.strptime(hd, "%a %d %b %y")
                    if sd <= dt <= ed:
                        lessons.append(L)
                except:
                    pass
            result.append({
                "id": f["id"],
                "name": f["name"],
                "lessons": lessons,
                "token_counts": [len(ENCODER.encode(L)) for L in lessons]
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/docs/search_content")
def search_content():
    try:
        q = request.args.get("query", "").strip()
        n = int(request.args.get("n", 5))
        st = [s.strip() for s in request.args.get("student", "").split(",") if s.strip()]

        resp = DRIVE.files().list(
            q=f"fullText contains '{q}' and mimeType='application/vnd.google-apps.document'",
            pageSize=n, fields="files(id,name)"
        ).execute().get("files", [])
        files = filter_by_students(resp, st)

        out = []
        for f in files:
            lesson_hits = [
                L for L in parse_lessons(extract_text(DOCS.documents().get(documentId=f["id"]).execute()))
                if q.lower() in L.lower()
            ][:n]
            out.append({
                "id": f["id"],
                "name": f["name"],
                "lessons": lesson_hits,
                "token_counts": [len(ENCODER.encode(L)) for L in lesson_hits]
            })
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- Index endpoints ----

@app.route("/docs/index/read")
def read_index_json():
    file_id = request.args.get("file_id", "").strip()
    if not file_id:
        return jsonify({"error": "Missing file_id"}), 400
    try:
        data = DRIVE.files().get_media(fileId=file_id).execute()
        return jsonify(json.loads(data.decode("utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/docs/index/update", methods=["POST"])
def update_index_json():
    """
    Creates or updates a per-student index JSON in Drive.
    Expects JSON body: { doc_id: "...", student: "...", index_file_id?: "..." }
    """
    try:
        payload       = request.get_json() or {}
        doc_id        = payload.get("doc_id", "").strip()
        student       = payload.get("student", "").strip()
        existing_id   = payload.get("index_file_id", "").strip()

        if not doc_id or not student:
            return jsonify({"error": "Missing doc_id or student"}), 400

        # 1) Fetch and parse lessons
        doc_json = DOCS.documents().get(documentId=doc_id).execute()
        lessons  = parse_lessons(extract_text(doc_json))

        # 2) Build index entries
        entries = []
        for L in lessons:
            lines   = L.splitlines()
            date    = lines[0]
            summary = " ".join(lines[1:3])  # first two lines as summary
            words   = re.findall(r"\b\w+\b", L.lower())
            freq    = Counter(w for w in words if len(w)>3)
            keywords= [w for w,_ in freq.most_common(10)]
            entries.append({"date": date, "summary": summary, "keywords": keywords})

        index_json = {
            "student":  student,
            "doc_id":   doc_id,
            "updated":  datetime.utcnow().isoformat() + "Z",
            "entries":  entries
        }

        # 3) Upload to Drive
        bio   = io.BytesIO(json.dumps(index_json, indent=2).encode("utf-8"))
        media = MediaIoBaseUpload(bio, mimetype="application/json")
        if existing_id:
            f = DRIVE.files().update(fileId=existing_id, media_body=media).execute()
            new_id = f.get("id")
        else:
            meta = {"name": f"{student}-lesson-index.json", "mimeType": "application/json"}
            f = DRIVE.files().create(body=meta, media_body=media, fields="id").execute()
            new_id = f.get("id")

        return jsonify({"index_file_id": new_id, "entry_count": len(entries)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- Run ----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
