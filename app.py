import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
import tiktoken
import re

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
    """
    Split a block of text into lessons by date headings.
    Returns list of strings, each starting with a heading line.
    """
    lines = text_block.splitlines()
    lessons = []
    current = []
    for line in lines:
        if DATE_HEADING_RE.match(line.strip()):
            if current:
                lessons.append("\n".join(current).strip())
            current = [line.strip()]
        else:
            current.append(line)
    if current:
        lessons.append("\n".join(current).strip())
    return lessons


@app.route("/docs/last_lessons")
def get_last_lessons():
    """
    Fetch the last `n` dated lessons for each student document.
    Query parameters:
      - n        (int, default=3): how many lessons per doc
      - weekday  (str, optional): e.g. "Friday" to filter only Friday docs
    """
    n = int(request.args.get("n", 3))
    weekday = request.args.get("weekday", "").strip()
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    docs_svc = build("docs", "v1", credentials=creds)

    # 1) List only lesson-note docs
    response = drive.files().list(
        q="mimeType='application/vnd.google-apps.document' and name contains ' - Violin Practice'",
        fields="files(id,name)"
    ).execute()
    files = response.get("files", [])

    # 2) Optionally filter by weekday
    if weekday:
        files = [f for f in files if weekday in f["name"]]

    results = []
    # 3) For each doc, page through paragraphs until we collect n lessons
    for f in files:
        doc_id = f["id"]
        name = f["name"]
        lessons = []
        start_par = 0

        while len(lessons) < n:
            doc = docs_svc.documents().get(documentId=doc_id).execute()
            paras = doc.get("body", {}).get("content", [])[start_par : start_par + 50]
            text_block = "".join(
                run["textRun"]["content"]
                for p in paras if "paragraph" in p
                for run in p["paragraph"].get("elements", [])
                if "textRun" in run
            )
            new_lessons = parse_lessons(text_block)
            # append any lessons we haven't seen yet
            for lesson in new_lessons:
                if len(lessons) < n:
                    lessons.append(lesson)
            # advance or break
            if len(lessons) >= n or len(paras) < 50:
                break
            start_par += 50

        results.append({
            "id": doc_id,
            "name": name,
            "lessons": lessons[:n],
            "token_counts": [len(ENCODER.encode(l)) for l in lessons[:n]]
        })

    return jsonify(results)


# ... keep your existing endpoints below unchanged ...
# /docs, /docs/all, /docs/{doc_id}, /docs/batch, /docs/{doc_id}/page, /docs/metadata

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
