import os
import json
import flask
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

# Scopes for full Drive and Docs access
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

# Load credentials from token.json
creds = None
if os.path.exists("token.json"):
    with open("token.json", "r") as token:
        creds_data = json.load(token)
        creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)

# Endpoint: Root check
@app.route("/", methods=["GET"])
def index():
    return "GPT Docs Proxy is running"

# Endpoint: List all Google Docs in Drive
@app.route("/docs/all", methods=["GET"])
def list_all_docs():
    service = build("drive", "v3", credentials=creds)
    results = (
        service.files()
        .list(q="mimeType='application/vnd.google-apps.document'", pageSize=1000)
        .execute()
    )
    items = results.get("files", [])
    return jsonify(items)

# Endpoint: Search for docs by partial title
@app.route("/docs", methods=["GET"])
def search_docs():
    title = request.args.get("title", "")
    if not title:
        return jsonify({"error": "Missing title query parameter"}), 400
    service = build("drive", "v3", credentials=creds)
    results = (
        service.files()
        .list(
            q=f"mimeType='application/vnd.google-apps.document' and name contains '{title}'",
            pageSize=10,
        )
        .execute()
    )
    items = results.get("files", [])
    return jsonify(items)

# Endpoint: Get content of a Google Doc by ID
@app.route("/docs/<doc_id>", methods=["GET"])
def get_doc_content(doc_id):
    docs_service = build("docs", "v1", credentials=creds)
    doc = docs_service.documents().get(documentId=doc_id).execute()

    content = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for el in element["paragraph"].get("elements", []):
                if "textRun" in el:
                    content += el["textRun"].get("content", "")
    return jsonify({"title": doc.get("title"), "content": content})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

