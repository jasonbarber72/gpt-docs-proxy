import os
import json
import logging
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from dotenv import load_dotenv
import numpy as np

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
openai_client = None

# Initialize OpenAI client
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully")
else:
    logger.warning("OpenAI API key not found")

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
            pageSize=50,
            fields="files(id, name, createdTime, modifiedTime)"
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

@app.route('/search', methods=['POST'])
def search_documents():
    """Search documents using semantic search"""
    try:
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"detail": "query is required in request body"}), 400
        
        query = data['query']
        student = data.get('student', '')
        n = data.get('n', 5)
        
        if not openai_client:
            return jsonify({"detail": "OpenAI API key not configured"}), 500
        
        initialize_google_services()
        
        if not drive_service:
            return jsonify({"detail": "Google Drive service not initialized"}), 500
        
        # Get all documents
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document'",
            pageSize=50,
            fields="files(id, name, createdTime, modifiedTime)"
        ).execute()
        
        documents = results.get('files', [])
        
        if not documents:
            return jsonify({"results": [], "total": 0})
        
        # Generate query embedding
        try:
            query_response = openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=query
            )
            query_embedding = np.array(query_response.data[0].embedding)
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            return jsonify({"detail": f"Error generating query embedding: {str(e)}"}), 500
        
        # Calculate similarity scores
        search_results = []
        for doc in documents:
            try:
                # Get document content
                if not docs_service:
                    continue
                    
                document = docs_service.documents().get(documentId=doc['id']).execute()
                
                # Extract text content
                content = ""
                if 'body' in document and 'content' in document['body']:
                    for element in document['body']['content']:
                        if 'paragraph' in element:
                            paragraph = element['paragraph']
                            if 'elements' in paragraph:
                                for elem in paragraph['elements']:
                                    if 'textRun' in elem:
                                        content += elem['textRun']['content']
                
                if not content.strip():
                    continue
                
                # Generate document embedding
                doc_response = openai_client.embeddings.create(
                    model="text-embedding-ada-002",
                    input=content[:8000]  # Limit to avoid token limits
                )
                doc_embedding = np.array(doc_response.data[0].embedding)
                
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, doc_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
                )
                
                search_results.append({
                    "document": {
                        "id": doc['id'],
                        "name": doc['name'],
                        "created_time": doc.get('createdTime', ''),
                        "modified_time": doc.get('modifiedTime', '')
                    },
                    "similarity": float(similarity),
                    "content": content[:500] + "..." if len(content) > 500 else content
                })
                
            except Exception as e:
                logger.error(f"Error processing document {doc['id']}: {e}")
                continue
        
        # Sort by similarity and apply limit
        search_results.sort(key=lambda x: x['similarity'], reverse=True)
        search_results = search_results[:n]
        
        return jsonify({
            "query": query,
            "student": student,
            "results": search_results,
            "total": len(search_results)
        })
        
    except Exception as e:
        logger.error(f"Error in search_documents: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
