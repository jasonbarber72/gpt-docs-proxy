import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secret-key")

SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]

def get_credentials():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )
    return creds

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
    docs = build("docs", "v1", credentials=creds)

    file = drive.files().get(fileId=doc_id, fields="name").execute()
    name = file.get("name")
    doc = docs.documents().get(documentId=doc_id).execute()
    text = extract_text(doc)

    return jsonify({"id": doc_id, "name": name, "text": text})

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    data = request.get_json() or {}
    doc_ids = data.get("doc_ids", [])
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)

    results = []
    for doc_id in doc_ids:
        file = drive.files().get(fileId=doc_id, fields="name").execute()
        name = file.get("name")
        doc = docs.documents().get(documentId=doc_id).execute()
        text = extract_text(doc)
        results.append({"id": doc_id, "name": name, "text": text})

    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
