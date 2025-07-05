import os
import json
import flask
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

SCOPES = [
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/documents'
]

CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'
creds = None

if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

@app.route("/authorize")
def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds_local = flow.run_local_server(port=8765, prompt='consent')
    with open(TOKEN_FILE, "w") as token:
        token.write(creds_local.to_json())
    return "Authorization complete. You may now close this tab."

@app.route("/docs", methods=["GET"])
def search_docs():
    title = request.args.get("title", "")
    service = build("drive", "v3", credentials=creds)
    results = service.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)",
    ).execute()
    items = results.get("files", [])
    return jsonify(items)

@app.route("/docs/all", methods=["GET"])
def list_all_docs():
    service = build("drive", "v3", credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)",
        pageSize=1000,
    ).execute()
    items = results.get("files", [])
    return jsonify(items)

@app.route("/docs/<doc_id>", methods=["GET"])
def read_doc(doc_id):
    service = build("docs", "v1", credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()
    text = ""
    for content in doc.get("body", {}).get("content", []):
        if "paragraph" in content:
            for element in content["paragraph"].get("elements", []):
                text += element.get("textRun", {}).get("content", "")
    return jsonify({"text": text})

@app.route("/docs/<doc_id>/write", methods=["POST"])
def write_doc(doc_id):
    data = request.get_json()
    text = data.get("text", "")
    service = build("docs", "v1", credentials=creds)
    requests = [
        {"insertText": {"location": {"index": 1}, "text": text + "\n\n"}}
    ]
    result = service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return jsonify({"status": "success", "response": result})

@app.route("/docs/batch-read", methods=["POST"])
def batch_read_docs():
    data = request.get_json()
    doc_ids = data.get("doc_ids", [])
    service = build("docs", "v1", credentials=creds)
    results = []

    for doc_id in doc_ids:
        try:
            doc = service.documents().get(documentId=doc_id).execute()
            text = ""
            for content in doc.get("body", {}).get("content", []):
                if "paragraph" in content:
                    for element in content["paragraph"].get("elements", []):
                        text += element.get("textRun", {}).get("content", "")
            results.append({"id": doc_id, "text": text})
        except Exception as e:
            results.append({"id": doc_id, "error": str(e)})

    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    app.run(host="0.0.0.0", port=port)
