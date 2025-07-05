import os
import json
from flask import Flask, request, jsonify, redirect, render_template_string
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
app = Flask(__name__)
CORS(app)

TOKEN_FILE = 'token.json'
CLIENT_SECRET_FILE = 'client_secret.json'

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
def home():
    return "GPT Docs Proxy is live."

@app.route("/authorize", methods=["GET", "POST"])
def authorize():
    if request.method == "POST":
        code = request.form.get("code")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        flow.fetch_token(code=code)
        creds = flow.credentials
        save_credentials(creds)
        return "Authorization successful. You can now close this tab."
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        auth_url, _ = flow.authorization_url(prompt='consent')
        return render_template_string("""
            <h2>Step 1: Click the link below to authorize</h2>
            <a href="{{auth_url}}" target="_blank">Authorize Google Access</a>
            <h2>Step 2: Paste the authorization code here</h2>
            <form method="post">
              <input name="code" type="text" style="width:400px"/>
              <input type="submit" value="Submit"/>
            </form>
        """, auth_url=auth_url)

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
