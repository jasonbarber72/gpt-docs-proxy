from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents'
]
TOKEN_FILE = 'token.json'
creds = None

if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

@app.route('/docs', methods=['GET'])
def search_docs():
    if not creds or not creds.valid:
        return jsonify({'error': 'Google credentials missing or invalid'}), 401

    title = request.args.get('title')
    if not title:
        return jsonify({'error': 'Missing title parameter'}), 400

    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q=f"name contains '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)"
    ).execute()

    return jsonify(results.get('files', []))

@app.route('/docs/all', methods=['GET'])
def list_docs():
    if not creds or not creds.valid:
        return jsonify({'error': 'Google credentials missing or invalid'}), 401

    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)",
        pageSize=1000
    ).execute()

    return jsonify(results.get('files', []))

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    if not creds or not creds.valid:
        return jsonify({'error': 'Google credentials missing or invalid'}), 401

    service = build('docs', 'v1', credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()

    text = ''
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph:
            for el in paragraph.get("elements", []):
                text += el.get("textRun", {}).get("content", '')

    return jsonify({'text': text.strip()})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_doc(doc_id):
    if not creds or not creds.valid:
        return jsonify({'error': 'Google credentials missing or invalid'}), 401

    text = request.json.get('text')
    if not text:
        return jsonify({'error': 'Missing text in request'}), 400

    service = build('docs', 'v1', credentials=creds)
    service.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": text + "\n"
                    }
                }
            ]
        }
    ).execute()

    return jsonify({'status': 'success'})

@app.route('/docs/batch-read', methods=['POST'])
def batch_read_docs():
    if not creds or not creds.valid:
        return jsonify({'error': 'Google credentials missing or invalid'}), 401

    doc_ids = request.json.get('doc_ids', [])
    if not doc_ids:
        return jsonify({'error': 'Missing doc_ids'}), 400

    service = build('docs', 'v1', credentials=creds)
    results = []

    for doc_id in doc_ids:
        try:
            doc = service.documents().get(documentId=doc_id).execute()
            text = ''
            for element in doc.get("body", {}).get("content", []):
                paragraph = element.get("paragraph")
                if paragraph:
                    for el in paragraph.get("elements", []):
                        text += el.get("textRun", {}).get("content", '')
            results.append({"id": doc_id, "text": text.strip()})
        except Exception as e:
            results.append({"id": doc_id, "text": "", "error": str(e)})

    return jsonify(results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
