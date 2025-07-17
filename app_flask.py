import os
import json
import logging
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly"
]

# Global services
docs_service = None
drive_service = None

def initialize_google_services():
    global docs_service, drive_service
    
    if docs_service is not None:
        return
    
    # Check environment variable first
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if service_account_json:
        try:
            logger.info("Attempting to use service account from environment variable")
            service_account_info = json.loads(service_account_json)
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES
            )
            
            docs_service = build("docs", "v1", credentials=creds)
            drive_service = build("drive", "v3", credentials=creds)
            logger.info("Successfully initialized Google services from environment")
            return
            
        except Exception as e:
            logger.error(f"Failed to initialize from environment: {e}")
    
    # Try local file as fallback
    if os.path.exists("service-account.json"):
        try:
            logger.info("Attempting to use local service account file")
            creds = service_account.Credentials.from_service_account_file(
                "service-account.json", scopes=SCOPES
            )
            
            docs_service = build("docs", "v1", credentials=creds)
            drive_service = build("drive", "v3", credentials=creds)
            logger.info("Successfully initialized Google services from local file")
            return
            
        except Exception as e:
            logger.error(f"Failed to initialize from local file: {e}")
    
    logger.error("No valid Google credentials found")

@app.route('/')
def home():
    return jsonify({
        "name": "GPT Google Docs Proxy",
        "status": "ok",
        "debug": {
            "has_env_var": bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
            "has_local_file": os.path.exists("service-account.json"),
            "openai_configured": bool(OPENAI_API_KEY)
        }
    })

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/docs/all')
def list_all_docs():
    try:
        initialize_google_services()
        
        if not drive_service:
            return jsonify({"detail": "Google Drive service not initialized"}), 500
        
        # Test query
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document'",
            pageSize=2,
            fields="files(id, name)"
        ).execute()
        
        documents = results.get('files', [])
        
        return jsonify({
            "documents": documents,
            "total": len(documents),
            "status": "success"
        })
        
    except Exception as e:
        logger.error(f"Error in list_all_docs: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route('/docs/read')
def read_document():
    try:
        file_id = request.args.get('file_id')
        if not file_id:
            return jsonify({"detail": "file_id parameter required"}), 400
        
        initialize_google_services()
        
        if not docs_service:
            return jsonify({"detail": "Google Docs service not initialized"}), 500
        
        # Get document
        document = docs_service.documents().get(documentId=file_id).execute()
        
        # Extract text
        content = ""
        if 'body' in document and 'content' in document['body']:
            for element in document['body']['content']:
                if 'paragraph' in element:
                    paragraph = element['paragraph']
                    if 'elements' in paragraph:
                        for elem in paragraph['elements']:
                            if 'textRun' in elem:
                                content += elem['textRun']['content']
        
        return jsonify({
            "file_id": file_id,
            "content": content,
            "status": "success"
        })
        
    except Exception as e:
        logger.error(f"Error in read_document: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
