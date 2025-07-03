from flask import Flask, request, jsonify
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os

app = Flask(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.readonly'
]
TOKEN_FILE = 'token.json'
CREDS_FILE = 'credentials.json'

def get_creds():
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        return creds
    else:
        # Do NOT prompt on server — just return error response
        raise RuntimeError("Missing token.json. Please authorize this app locally first.")

@app.route('/docs', methods=['GET'])
def search_doc_by_name():
    title = request.args.get('title')
    try:
        creds = get_creds()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    drive_service = build('drive', 'v3', credentials=creds)
    results = drive_service.files().list(
        q=f"name = '{title}' and mimeType='application/vnd.google-apps.document'",
        fields="files(id, name)", pageSize=1
    ).execute()
    files = results.get('files', [])
    return jsonify(files)

@app.route('/docs/<doc_id>', methods=['GET'])
def read_doc(doc_id):
    try:
        creds = get_creds()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    docs_service = build('docs', 'v1', credentials=creds)
    document = docs_service.documents().get(documentId=doc_id).execute()

    text = []
    for element in document.get('body', {}).get('content', []):
        paragraph = element.get('paragraph')
        if not paragraph:
            continue
        for el in paragraph.get('elements', []):
            text_run = el.get('textRun')
            if text_run:
                text.append(text_run['content'])
    return jsonify({'text': ''.join(text)})

@app.route('/docs/<doc_id>/write', methods=['POST'])
def write_to_doc(doc_id):
    data = request.json
    text = data.get('text', '')

    try:
        creds = get_creds()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    docs_service = build('docs', 'v1', credentials=creds)
    requests = [{
        'insertText': {
            'location': {'index': 1},
            'text': text
        }
    }]
    result = docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()
    return jsonify({"status": "success", "result": result})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
