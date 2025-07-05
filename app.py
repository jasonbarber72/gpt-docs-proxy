from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import json

app = Flask(__name__)
CORS(app)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
]

CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'

def get_credentials():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as token:
            creds_data = json.load(token)
            creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    else:
        creds = None
    return creds

@app.route('/authorize')
def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=8765)
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    return 'Authorization complete. You may now close this tab.'

@app.route('/docs', methods=['GET'])
def search_docs():
    title = request.args.get('title')
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q=f"mimeType='application/vnd.google-apps.document' and name contains '{title}'",
        pageSize=10, fields="files(id, name)").execute()
    files = results.get('files', [])
    return jsonify(files)

@app.route('/docs/all', methods=['GET'])
def list_all_docs():
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=1000, fields="files(id, name)").execute()
    files = results.get('files', [])
    return jsonify(files)

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    document = service.documents().get(documentId=doc_id).execute()
    text = ''
    for element in document.get('body').get('content'):
        if 'paragraph' in element:
            for item in element['paragraph'].get('elements', []):
                text += item.get('textRun', {}).get('content', '')
    return jsonify({'text': text})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_doc(doc_id):
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    data = request.get_json()
    text = data.get('text', '')
    requests_body = [
        {'insertText': {
            'location': {'index': 1},
            'text': text
        }}
    ]
    result = service.documents().batchUpdate(
        documentId=doc_id, body={'requests': requests_body}).execute()
    return jsonify({'status': 'success', 'updates': result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
