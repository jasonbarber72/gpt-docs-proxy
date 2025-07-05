import os
import json
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

app = Flask(__name__)
CORS(app)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'
REDIRECT_URI = "https://gpt-docs-proxy.onrender.com/oauth2callback"

def save_credentials(creds):
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

def load_credentials():
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        try:
            creds.refresh(build('drive', 'v3', credentials=creds)._http.request)
        except RefreshError:
            return None
        return creds
    return None

@app.route("/")
def index():
    return "GPT Docs Proxy is running."

@app.route("/authorize")
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt='consent', include_granted_scopes='true')
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)

    creds = flow.credentials
    save_credentials(creds)
    return "Authorization complete. You may now close this tab."

@app.route("/docs")
def search_docs():
    creds = load_credentials()
    if not creds:
        return "Not authorized", 401
    service = build('drive', 'v3', credentials=creds)
    title = request.args.get('title')
    results = service.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        pageSize=10,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))

@app.route("/docs/<doc_id>")
def get_doc(doc_id):
    creds = load_credentials()
    if not creds:
        return "Not authorized", 401
    docs_service = build('docs', 'v1', credentials=creds)
    doc = docs_service.documents().get(documentId=doc_id).execute()
    return jsonify(doc)

@app.route("/docs/all")
def list_all_docs():
    creds = load_credentials()
    if not creds:
        return "Not authorized", 401
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=100,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
