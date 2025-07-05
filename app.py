from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import json

app = Flask(__name__)
CORS(app)

SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'

creds = None
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, 'r') as token:
        creds_data = json.load(token)
        creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)

@app.route('/authorize')
def authorize():
    global creds
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_console()

    # Save the credentials
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

    return 'Authorization complete. Credentials saved.'

@app.route('/docs', methods=['GET'])
def search_docs():
    title = request.args.get('title')
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)"
    ).execute()
    items = results.get('files', [])
    return jsonify(items)

@app.route('/docs/all', methods=['GET'])
def list_docs():
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)"
    ).execute()
    items = results.get('files', [])
    return jsonify(items)

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    service = build('docs', 'v1', credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()
    text = ''
    for content in doc.get('body').get('content'):
        if 'paragraph' in content:
            for element in content['paragraph'].get('elements', []):
                text += element.get('textRun', {}).get('content', '')
    return jsonify({'text': text})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_doc(doc_id):
    data = request.json
    text = data.get('text')
    service = build('docs', 'v1', credentials=creds)
    requests_body = [
        {
            'insertText': {
                'location': {
                    'index': 1,
                },
                'text': text + '\n'
            }
        }
    ]
    result = service.documents().batchUpdate(
        documentId=doc_id, body={'requests': requests_body}).execute()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
