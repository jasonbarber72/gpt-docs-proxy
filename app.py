import os
import json
import flask
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

CLIENT_SECRET_FILE = 'client_secret.json'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents']
TOKEN_FILE = 'token.json'
REDIRECT_URI = 'https://gpt-docs-proxy.onrender.com/oauth2callback'

@app.route('/')
def index():
    return 'GPT Docs Proxy is running.'

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    flask.session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = flask.session.get('state')
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)

    creds = flow.credentials
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

    return 'Authorization complete. You may close this tab.'

def load_credentials():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as token:
            creds_data = json.load(token)
            return Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    return None

@app.route('/docs', methods=['GET'])
def search_docs():
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Missing credentials'}), 403

    service = build('drive', 'v3', credentials=creds)
    title_query = request.args.get('title')
    query = f"name contains '{title_query}' and mimeType='application/vnd.google-apps.document' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return jsonify(results.get('files', []))

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Missing credentials'}), 403

    docs_service = build('docs', 'v1', credentials=creds)
    document = docs_service.documents().get(documentId=doc_id).execute()
    return jsonify(document)

@app.route('/docs/all', methods=['GET'])
def list_all_docs():
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Missing credentials'}), 403

    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document' and trashed = false",
        pageSize=100,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))

@app.route('/docs/batch', methods=['POST'])
def read_batch_docs():
    creds = load_credentials()
    if not creds:
        return jsonify({'error': 'Missing credentials'}), 403

    doc_ids = request.json.get('doc_ids', [])
    docs_service = build('docs', 'v1', credentials=creds)
    documents = []
    for doc_id in doc_ids:
        document = docs_service.documents().get(documentId=doc_id).execute()
        documents.append(document)
    return jsonify(documents)

if __name__ == '__main__':
    app.secret_key = 'your_secret_key_here'
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
