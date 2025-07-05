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
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file',
]
CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'


def get_credentials():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as token:
            creds_data = json.load(token)
            return Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    return None


@app.route('/authorize')
def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=8765)
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    return 'Authorization complete. You may now close this tab.'


@app.route('/docs', methods=['GET'])
def search_docs():
    title_query = request.args.get('title', '')
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q=f"name contains '{title_query}' and mimeType='application/vnd.google-apps.document'",
        pageSize=10,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))


@app.route('/docs/all', methods=['GET'])
def list_all_docs():
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=1000,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))


@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()
    text = ''
    for element in doc.get('body', {}).get('content', []):
        if 'paragraph' in element:
            for p in element['paragraph'].get('elements', []):
                text += p.get('textRun', {}).get('content', '')
    return jsonify({'text': text})


@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_to_doc(doc_id):
    data = request.json
    text = data.get('text', '')
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    requests_body = {
        'requests': [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': text
                }
            }
        ]
    }
    result = service.documents().batchUpdate(documentId=doc_id, body=requests_body).execute()
    return jsonify({'status': 'success', 'response': result})


@app.route('/docs/batch-read', methods=['POST'])
def read_multiple_docs():
    data = request.json
    doc_ids = data.get('doc_ids', [])
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    results = []

    for doc_id in doc_ids:
        try:
            doc = service.documents().get(documentId=doc_id).execute()
            text = ''
            for element in doc.get('body', {}).get('content', []):
                if 'paragraph' in element:
                    for p in element['paragraph'].get('elements', []):
                        text += p.get('textRun', {}).get('content', '')
            results.append({'id': doc_id, 'text': text})
        except Exception as e:
            results.append({'id': doc_id, 'error': str(e)})

    return jsonify(results)


if __name__ == '__main__':
    app.run(port=8765)
