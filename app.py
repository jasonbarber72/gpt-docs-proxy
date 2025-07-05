from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import os
import json
import google.auth
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

CLIENT_SECRET_FILE = 'client_secret.json'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/documents']
REDIRECT_URI = 'https://gpt-docs-proxy.onrender.com/oauth2callback'

creds = None

# Load existing credentials if available
if os.path.exists('token.json'):
    with open('token.json', 'r') as token_file:
        creds_data = json.load(token_file)
        creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)

def save_credentials(creds):
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    global creds
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)

    creds = flow.credentials
    save_credentials(creds)
    return 'Authorization complete. You may now close this tab.'

def get_drive_service():
    global creds
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
        else:
            raise Exception("Google credentials are missing or invalid.")
    return build('drive', 'v3', credentials=creds)

def get_docs_service():
    global creds
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
        else:
            raise Exception("Google credentials are missing or invalid.")
    return build('docs', 'v1', credentials=creds)

@app.route('/docs', methods=['GET'])
def search_docs():
    query_title = request.args.get('title')
    if not query_title:
        return jsonify({'error': 'Missing title parameter'}), 400

    service = get_drive_service()
    response = service.files().list(
        q=f"name contains '{query_title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)"
    ).execute()

    return jsonify(response.get('files', []))

@app.route('/docs/all', methods=['GET'])
def list_all_docs():
    service = get_drive_service()
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=100,
        fields="files(id, name)"
    ).execute()
    return jsonify(results.get('files', []))

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    docs_service = get_docs_service()
    doc = docs_service.documents().get(documentId=doc_id).execute()
    content = []

    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for elem in element["paragraph"].get("elements", []):
                text = elem.get("textRun", {}).get("content", "")
                content.append(text)

    return jsonify({"text": "".join(content)})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_doc(doc_id):
    data = request.get_json()
    text = data.get('text', '')
    if not text:
        return jsonify({'error': 'Missing text field'}), 400

    docs_service = get_docs_service()
    requests = [
        {
            "insertText": {
                "location": {
                    "index": 1
                },
                "text": text + "\n"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return jsonify({'status': 'success'})

@app.route('/docs/batch-read', methods=['POST'])
def batch_read_docs():
    data = request.get_json()
    doc_ids = data.get('doc_ids', [])
    if not doc_ids:
        return jsonify({'error': 'Missing doc_ids field'}), 400

    docs_service = get_docs_service()
    results = []
    for doc_id in doc_ids:
        try:
            doc = docs_service.documents().get(documentId=doc_id).execute()
            content = []
            for element in doc.get("body", {}).get("content", []):
                if "paragraph" in element:
                    for elem in element["paragraph"].get("elements", []):
                        text = elem.get("textRun", {}).get("content", "")
                        content.append(text)
            results.append({'id': doc_id, 'text': ''.join(content)})
        except Exception as e:
            results.append({'id': doc_id, 'error': str(e)})

    return jsonify(results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
