import os

# ── Allow HTTP (insecure) transport for OAuthlib on this server ─────────────────
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

import json
import logging
from flask import Flask, request, jsonify, redirect, render_template_string
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

# ── Flask App Setup ────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
REDIRECT_URI = 'https://gpt-docs-proxy.onrender.com/oauth2callback'

# ── Helper Functions ───────────────────────────────────────────────────────────
def save_credentials(creds: Credentials):
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())
    app.logger.info("Saved new credentials to token.json")

def load_credentials() -> Credentials | None:
    if not os.path.exists(TOKEN_FILE):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
            app.logger.info("Refreshed expired credentials")
        except RefreshError as e:
            app.logger.error(f"Failed to refresh credentials: {e}")
            return None
    return creds

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return 'GPT Docs Proxy is live.'

@app.route('/authorize')
def authorize():
    """
    Step 1: Redirect the user to Google's OAuth consent screen.
    """
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    """
    Step 2: Google redirects back here with a code; exchange it for tokens.
    """
    try:
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        save_credentials(creds)
        return '✅ Authorization complete. You may now close this tab.'
    except Exception as e:
        app.logger.exception("Error in OAuth callback")
        return (
            f"<h2>OAuth Callback Error</h2>"
            f"<pre>{e}</pre>"
            f"<p>See Render logs for full traceback.</p>",
            500
        )

@app.route('/docs')
def search_docs():
    """
    Search for Google Docs by partial title.
    """
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Not authorized'}), 401

    title = request.args.get('title', '')
    if not title:
        return jsonify({'error': 'Missing ?title parameter'}), 400

    drive = build('drive', 'v3', credentials=creds)
    results = drive.files().list(
        q=(
            f"mimeType='application/vnd.google-apps.document' "
            f"and name contains '{title}' and trashed=false"
        ),
        pageSize=10,
        fields="files(id, name)"
    ).execute()

    return jsonify(results.get('files', []))

@app.route('/docs/all')
def list_all_docs():
    """
    List all accessible Google Docs.
    """
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Not authorized'}), 401

    drive = build('drive', 'v3', credentials=creds)
    results = drive.files().list(
        q="mimeType='application/vnd.google-apps.document' and trashed=false",
        pageSize=1000,
        fields="files(id, name)"
    ).execute()

    return jsonify(results.get('files', []))

@app.route('/docs/<doc_id>')
def get_doc_content(doc_id):
    """
    Return the full text content of a single Google Doc.
    """
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Not authorized'}), 401

    docs = build('docs', 'v1', credentials=creds)
    document = docs.documents().get(documentId=doc_id).execute()

    # Extract plain text
    text = ''
    for element in document.get('body', {}).get('content', []):
        if 'paragraph' in element:
            for run in element['paragraph'].get('elements', []):
                text += run.get('textRun', {}).get('content', '')

    return jsonify({'id': doc_id, 'text': text})

# ── Run on Render ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
