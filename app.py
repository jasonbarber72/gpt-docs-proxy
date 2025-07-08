import os
import re
import json
import io
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
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
    DOCS  = build("docs",  "v1", credentials=creds)

def extract_text(doc):
    text = ""
    for el in doc.get("body",{}).get("content",[]):
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

@app.route("/docs")
def search_docs_by_title():
    title = request.args.get("title","").strip()
    if not title:
        return jsonify([]),400
    resp = DRIVE.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute()
    return jsonify(resp.get("files",[]))

@app.route("/docs/all")
def list_all_docs():
    files = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute().get("files",[])
    return jsonify(files)

@app.route("/docs/<doc_id>")
def read_doc_by_id(doc_id):
    file = DRIVE.files().get(fileId=doc_id,fields="name").execute()
    doc  = DOCS.documents().get(documentId=doc_id).execute()
    text = extract_text(doc)
    return jsonify({
        "id":doc_id,
        "name":file["name"],
        "text":text,
        "char_count":len(text),
        "token_count":len(ENCODER.encode(text))
    })

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    ids = (request.get_json() or {}).get("doc_ids",[])
    out = []
    for i in range(0,len(ids),10):
        for did in ids[i:i+10]:
            file = DRIVE.files().get(fileId=did,fields="name").execute()
            doc  = DOCS.documents().get(documentId=did).execute()
            text = extract_text(doc)
            out.append({
                "id":did,
                "name":file["name"],
                "text":text,
                "char_count":len(text),
                "token_count":len(ENCODER.encode(text))
            })
    return jsonify(out)

@app.route("/docs/<doc_id>/page")
def read_doc_page(doc_id):
    s = int(request.args.get("start_par",0))
    e = int(request.args.get("end_par",s+50))
    doc = DOCS.documents().get(documentId=doc_id).execute()
    paras = doc["body"]["content"][s:e]
    text = "".join(
        run["textRun"]["content"]
        for p in paras if "paragraph" in p
        for run in p["paragraph"]["elements"]
        if "textRun" in run
    )
    return jsonify({
        "id":doc_id,
        "name":doc.get("title",""),
        "text":text,
        "char_count":len(text),
        "token_count":len(ENCODER.encode(text)),
        "next_start":e
    })

@app.route("/docs/metadata")
def list_docs_metadata():
    files = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute().get("files",[])
    meta = []
    for f in files:
        doc  = DOCS.documents().get(documentId=f["id"]).execute()
        text = extract_text(doc)
        meta.append({
            "id":f["id"],
            "name":f["name"],
            "char_count":len(text),
            "token_count":len(ENCODER.encode(text))
        })
    return jsonify(meta)

@app.route("/docs/last_lessons")
def get_last_lessons():
    n  = int(request.args.get("n",3))
    wd = request.args.get("weekday","").strip()
    st = [s.strip() for s in request.args.get("student","").split(",") if s.strip()]
    files = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute().get("files",[])
    if wd:
        files = [f for f in files if wd in f["name"]]
    if st:
        files = [f for f in files if any(s in f["name"] for s in st)]
    res = []
    for f in files:
        did,name = f["id"], f["name"]
        lessons, sp, err = [], 0, None
        try:
            while len(lessons) < n:
                d = DOCS.documents().get(documentId=did).execute()
                paras = d["body"]["content"][sp:sp+50]
                block = "".join(
                    run["textRun"]["content"]
                    for p in paras if "paragraph" in p
                    for run in p["paragraph"]["elements"]
                    if "textRun" in run
                )
                for L in parse_lessons(block):
                    if len(lessons) < n:
                        lessons.append(L)
                if len(paras) < 50:
                    break
                sp += 50
        except Exception as e:
            err = str(e)
        res.append({
            "id":did,
            "name":name,
            "lessons":lessons[:n],
            "token_counts":[len(ENCODER.encode(L)) for L in lessons[:n]],
            "error":err
        })
    return jsonify(res)

@app.route("/docs/lessons_in_range")
def get_lessons_in_range():
    sd = datetime.fromisoformat(request.args["start_date"])
    ed = datetime.fromisoformat(request.args["end_date"])
    wd = request.args.get("weekday","").strip()
    st = [s.strip() for s in request.args.get("student","").split(",") if s.strip()]
    files = DRIVE.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id,name)"
    ).execute().get("files",[])
    if wd:
        files = [f for f in files if wd in f["name"]]
    if st:
        files = [f for f in files if any(s in f["name"] for s in st)]
    res = []
    for f in files:
        did,name = f["id"], f["name"]
        lessons, sp, err = [], 0, None
        try:
            while True:
                d = DOCS.documents().get(documentId=did).execute()
                paras = d["body"]["content"][sp:sp+50]
                block = "".join(
                    run["textRun"]["content"]
                    for p in paras if "paragraph" in p
                    for run in p["paragraph"]["elements"]
                    if "textRun" in run
                )
                for L in parse_lessons(block):
                    hd = L.splitlines()[0]
                    try:
                        dt = datetime.strptime(hd,"%a %d %b %y")
                        if sd <= dt <= ed:
                            lessons.append(L)
                    except:
                        pass
                if len(paras) < 50:
                    break
                sp += 50
        except Exception as e:
            err = str(e)
        res.append({
            "id":did,
            "name":name,
            "lessons":lessons,
            "token_counts":[len(ENCODER.encode(L)) for L in lessons],
            "error":err
        })
    return jsonify(res)

@app.route("/docs/search_content")
def search_content():
    q  = request.args.get("query","").strip()
    n  = int(request.args.get("n",5))
    st = [s.strip() for s in request.args.get("student","").split(",") if s.strip()]
    resp = DRIVE.files().list(
        q=f"fullText contains '{q}' and mimeType='application/vnd.google-apps.document'",
        pageSize=n,
        fields="files(id,name)"
    ).execute().get("files",[])
    if st:
        resp = [f for f in resp if any(s in f["name"] for s in st)]
    res = []
    for f in resp:
        did,name = f["id"], f["name"]
        err, lessons = None, []
        try:
            doc = DOCS.documents().get(documentId=did).execute()
            text = extract_text(doc)
            for L in parse_lessons(text):
                if q.lower() in L.lower():
                    lessons.append(L)
                    if len(lessons) >= n:
                        break
        except Exception as e:
            err = str(e)
        res.append({
            "id":did,
            "name":name,
            "lessons":lessons,
            "token_counts":[len(ENCODER.encode(L)) for L in lessons],
            "error":err
        })
    return jsonify(res)

@app.route("/docs/index/update", methods=["POST"])
def update_index_json():
    data = request.get_json() or {}
    doc_id = data.get("doc_id")
    student = data.get("student")
    index_file_id = data.get("index_file_id")
    if not doc_id or not student:
        return jsonify({"error":"Missing doc_id or student"}),400
    try:
        doc = DOCS.documents().get(documentId=doc_id).execute()
        text = extract_text(doc)
        lessons = parse_lessons(text)
    except Exception as e:
        return jsonify({"error":str(e)}),500
    entries = []
    for L in lessons:
        lines = L.splitlines()
        date = lines[0] if lines else ""
        summary = " ".join(lines[1:]).strip() if len(lines)>1 else ""
        words = [w.strip(".,!?:;()\"'").lower() for w in summary.split()]
        keywords = []
        for w in words:
            if len(w)>4 and w not in keywords:
                keywords.append(w)
            if len(keywords)>=5:
                break
        entries.append({"date":date,"summary":summary,"keywords":keywords})
    content = json.dumps(entries, indent=2)
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="application/json")
    try:
        if index_file_id:
            DRIVE.files().update(fileId=index_file_id, media_body=media).execute()
            file_id = index_file_id
        else:
            file_metadata = {"name":f"{student}-lesson-index.json", "mimeType":"application/json"}
            res = DRIVE.files().create(body=file_metadata, media_body=media, fields="id").execute()
            file_id = res.get("id")
    except Exception as e:
        return jsonify({"error":str(e)}),500
    return jsonify({"file_id":file_id,"student":student,"entry_count":len(entries)})

@app.route("/docs/index/read")
def read_index_json():
    file_id = request.args.get("file_id","").strip()
    if not file_id:
        return jsonify({"error":"Missing file_id"}),400
    try:
        raw = DRIVE.files().get_media(fileId=file_id).execute()
        text = raw.decode("utf-8")
        return jsonify(json.loads(text))
    except Exception as e:
        return jsonify({"error":str(e)}),500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
