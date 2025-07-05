import os
import json
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]

CLIENT_SECRET_FILE = "client_secret.json"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_credentials():
    creds = None
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as token:
            creds_data = json.load(token)
            creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
        with open(CREDENTIALS_FILE, "w") as token:
            token.write(creds.to_json())
    return creds


@app.route("/authorize")
def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8765/"
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    return redirect(auth_url)


@app.route("/")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return "Missing authorization code", 400

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8765/"
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(CREDENTIALS_FILE, "w") as token:
        token.write(creds.to_json())

    return "✅ Authorization complete. You may now close this tab."


@app.route("/docs", methods=["GET"])
def search_docs_by_title():
    title = request.args.get("title")
    creds = get_credentials()
    if not creds:
        return jsonify({"error": "Unauthorized"}), 401

    service = build("drive", "v3", credentials=creds)
    results = service.files().list(
        q=f"mimeType='application/vnd.google-apps.document' and name contains '{title}'",
        fields="files(id, name)",
    ).execute()
    return jsonify(results.get("files", []))


@app.route("/docs/all", methods=["GET"])
def list_all_docs():
    creds = get_credentials()
    if not creds:
        return jsonify({"error": "Unauthorized"}), 401

    service = build("drive", "v3", credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)",
    ).execute()
    return jsonify(results.get("files", []))


@app.route("/docs/<doc_id>", methods=["GET"])
def read_doc(doc_id):
    creds = get_credentials()
    if not creds:
        return jsonify({"error": "Unauthorized"}), 401

    service = build("docs", "v1", credentials=creds)
    document = service.documents().get(documentId=doc_id).execute()

    text = ""
    for element in document.get("body", {}).get("content", []):
        text_run = element.get("paragraph", {}).get("elements", [{}])[0].get("textRun", {})
        text += text_run.get("content", "")

    return jsonify({"text": text})


@app.route("/docs/<doc_id>/write", methods=["POST"])
def write_to_doc(doc_id):
    data = request.get_json()
    text = data.get("text", "")

    creds = get_credentials()
    if not creds:
        return jsonify({"error": "Unauthorized"}), 401

    service = build("docs", "v1", credentials=creds)
    requests_body = {
        "requests": [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": text
                }
            }
        ]
    }
    result = service.documents().batchUpdate(
        documentId=doc_id,
        body=requests_body
    ).execute()

    return jsonify({"status": "success", "result": result})


if __name__ == "__main__":
    app.run(port=8765)
