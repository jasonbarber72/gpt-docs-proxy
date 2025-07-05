import os
import json
from flask import Flask, request, redirect, jsonify
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secret-key")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as token:
                token.write(creds.to_json())
        else:
            raise Exception("No valid credentials. Please re-authorize via /authorize.")
    return creds

def extract_text(doc):
    text = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                if "textRun" in run and run["textRun"].get("content"):
                    text += run["textRun"]["content"]
    return text

@app.route("/authorize")
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=os.environ.get("REDIRECT_URI")
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=os.environ.get("REDIRECT_URI")
    )
    flow.fetch_token(code=request.args.get("code"))
    creds = flow.credentials
    with open(TOKEN_FILE, "w") as token:
        token.write(creds.to_json())
    return "Authorization complete. You can now close this window."

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

    # Fetch name
    file = drive.files().get(fileId=doc_id, fields="name").execute()
    name = file.get("name")

    # Fetch and extract text
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
        # Fetch name
        file = drive.files().get(fileId=doc_id, fields="name").execute()
        name = file.get("name")
        # Fetch and extract text
        doc = docs.documents().get(documentId=doc_id).execute()
        text = extract_text(doc)
        results.append({"id": doc_id, "name": name, "text": text})

    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
