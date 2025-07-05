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

# Minimal scope for Drive file read-only access
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'

creds = None
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

def save_credentials(creds):
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

@app.route('/')
def index():
    return 'GPT Docs Proxy is running.'

@app.route('/authorize')
def authorize():
    global creds
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=8765)
    save_credentials(creds)
    return 'Authorization complete. You may now close this tab.'

@app.route('/docs')
def search_docs():
    if not creds or not creds.valid:
        return jsonify({'error': 'Invalid or missing credentials'}), 401

    query = request.args.get('title', '')
    if not query:
        return jsonify({'error': 'Missing required query parameter: title'}), 400

    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q=f"mimeType='application/vnd.google-apps.document' and name contains '{query}' and trashed=false",
        pageSize=10,
        fields="files(id, name)"
    ).execute()
    items = results.get('files', [])

    return jsonify(items)

@app.route('/docs/<doc_id>')
def get_doc(doc_id):
    if not creds or not creds.valid:
        return jsonify({'error': 'Invalid or missing credentials'}), 401

    docs_service = build('docs', 'v1', credentials=creds)
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        return jsonify(doc)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/docs/all')
def list_all_docs():
    if not creds or not creds.valid:
        return jsonify({'error': 'Invalid or missing credentials'}), 401

    drive_service = build('drive', 'v3', credentials=creds)
    try:
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document' and trashed=false",
            pageSize=100,
            fields="files(id, name)"
        ).execute()
        items = results.get('files', [])
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
