from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import io

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents']
TOKEN_FILE = 'token.json'
CLIENT_SECRET_FILE = 'client_secret.json'

# ------------------------------------
# Authorization Routes
# ------------------------------------

@app.route('/authorize')
def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    auth_url, _ = flow.authorization_url(prompt='consent')

    return f'''
        <html>
        <body>
            <h2>Step 1: Click the link below to authorize</h2>
            <a href="{auth_url}" target="_blank">Authorize Google Access</a>
            <form method="post" action="/oauth2callback">
                <h2>Step 2: Paste the authorization code here</h2>
                <input name="code" type="text" style="width:400px"/>
                <button type="submit">Submit</button>
            </form>
        </body>
        </html>
    '''

@app.route('/oauth2callback', methods=['POST'])
def oauth2callback():
    code = request.form['code']
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    flow.fetch_token(code=code)
    creds = flow.credentials
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    return "✅ Authorization complete. You may now close this tab."

# ------------------------------------
# Helper: Get credentials and service
# ------------------------------------

def get_credentials():
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Missing token.json. Visit /authorize first.")
    with open(TOKEN_FILE, 'r') as token:
        creds_data = json.load(token)
    creds = Credentials.from_authorized_user_info(info=creds_data)
    return creds

def get_drive_service():
    creds = get_credentials()
    return build('drive', 'v3', credentials=creds)

def get_docs_service():
    creds = get_credentials()
    return build('docs', 'v1', credentials=creds)

# ------------------------------------
# API: Search, List, Read, Write Docs
# ------------------------------------

@app.route('/docs', methods=['GET'])
def search_docs():
    title = request.args.get('title')
    service = get_drive_service()
    results = service.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    return jsonify(files)

@app.route('/docs/all', methods=['GET'])
def list_all_docs():
    service = get_drive_service()
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)",
        pageSize=1000
    ).execute()
    files = results.get('files', [])
    return jsonify(files)

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    text = ''
    for element in doc.get('body', {}).get('content', []):
        if 'paragraph' in element:
            for run in element['paragraph'].get('elements', []):
                if 'textRun' in run:
                    text += run['textRun'].get('content', '')
    return jsonify({'text': text})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_doc(doc_id):
    body = request.get_json()
    text = body.get('text', '')
    service = get_docs_service()
    requests = [
        {
            'insertText': {
                'location': {
                    'index': 1
                },
                'text': text + '\n'
            }
        }
    ]
    result = service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()
    return jsonify({'status': 'success'})

# ------------------------------------
# Start Server
# ------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
