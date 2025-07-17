import os
import json
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dateutil import parser
from flask import Flask, request, jsonify

# Google API imports
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

# OpenAI imports
from openai import OpenAI
import numpy as np
import tiktoken

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OAuth credentials
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") 
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly"
]

# Initialize Google API credentials
docs_service = None
drive_service = None

def initialize_google_services():
    """Initialize Google API services with OAuth authentication"""
    global docs_service, drive_service
    
    if docs_service is not None:
        return
    
    creds = None
    
    # Debug environment variables - v3
    logger.info(f"OAuth credentials present: CLIENT_ID={bool(GOOGLE_CLIENT_ID)}, CLIENT_SECRET={bool(GOOGLE_CLIENT_SECRET)}, REFRESH_TOKEN={bool(GOOGLE_REFRESH_TOKEN)}")
    
    # Try OAuth first if we have the credentials
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN:
        try:
            logger.info("Using OAuth authentication")
            creds = Credentials(
                token=None,
                refresh_token=GOOGLE_REFRESH_TOKEN,
                token_uri='https://accounts.google.com/o/oauth2/token',
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET
            )
            creds.refresh(Request())
            logger.info("OAuth token refreshed successfully")
        except Exception as e:
            logger.error(f"OAuth authentication failed: {e}")
            creds = None
    
    # Fallback to service account if OAuth fails
    if not creds:
        try:
            if os.path.exists(SERVICE_ACCOUNT_FILE):
                logger.info("Using service account from file")
                creds = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES
                )
            else:
                # Try to load from environment variable (for Render deployment)
                service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                if service_account_json:
                    try:
                        logger.info("Using service account from environment")
                        service_account_info = json.loads(service_account_json)
                        creds = service_account.Credentials.from_service_account_info(
                            service_account_info, scopes=SCOPES
                        )
                    except json.JSONDecodeError:
                        logger.error("Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON")
                        return
                else:
                    logger.error("No Google credentials found")
                    return
        except Exception as e:
            logger.error(f"Service account authentication failed: {e}")
            return
    
    try:
        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)
        logger.info("Google API services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Google API services: {e}")
        docs_service = None
        drive_service = None

# Initialize OpenAI client
openai_client = None
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully")

# Initialize tiktoken encoder for token counting
try:
    tokenizer = tiktoken.encoding_for_model("gpt-4")
except:
    tokenizer = tiktoken.get_encoding("cl100k_base")

# Flask app
app = Flask(__name__)

# Document cache
doc_cache = {}

def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken"""
    try:
        return len(tokenizer.encode(text))
    except:
        # Fallback estimation
        return int(len(text.split()) * 1.3)

def extract_student_name(filename: str) -> Optional[str]:
    """Extract student name from lesson document filename"""
    # Remove common suffixes and patterns
    cleaned = re.sub(r'- Violin Practice.*', '', filename)
    cleaned = re.sub(r'- violin practice.*', '', cleaned)
    cleaned = re.sub(r'Violin Practice.*', '', cleaned)
    cleaned = re.sub(r'violin practice.*', '', cleaned)
    cleaned = re.sub(r'- (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday).*', '', cleaned, flags=re.IGNORECASE)
    
    # Extract first part as student name
    parts = cleaned.split(' - ')
    if parts:
        return parts[0].strip()
    
    return filename.split(' - ')[0].strip() if ' - ' in filename else filename.strip()

def extract_lesson_date(content: str) -> Optional[str]:
    """Extract lesson date from document content"""
    lines = content.split('\n')[:10]  # Check first 10 lines
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Look for date patterns
        date_patterns = [
            r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # MM/DD/YYYY or M/D/YY
            r'\b\d{1,2}-\d{1,2}-\d{2,4}\b',  # MM-DD-YYYY or M-D-YY
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b',
            r'\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
            r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    parsed_date = parser.parse(match.group())
                    return parsed_date.strftime('%Y-%m-%d')
                except:
                    continue
    
    return None

def get_document_content(file_id: str) -> Optional[str]:
    """Get document content from Google Docs API"""
    initialize_google_services()
    if not docs_service:
        return None
    
    try:
        # Check cache first
        if file_id in doc_cache:
            logger.info(f"Document {file_id} found in cache")
            return doc_cache[file_id]
        
        # Get document from API
        document = docs_service.documents().get(documentId=file_id).execute()
        
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
        
        # Cache the document
        doc_cache[file_id] = content
        logger.info(f"Document {file_id} retrieved and cached")
        return content
        
    except Exception as e:
        logger.error(f"Error getting document {file_id}: {e}")
        return None

def get_all_documents() -> List[Dict[str, Any]]:
    """Get all documents from Google Drive"""
    initialize_google_services()
    if not drive_service:
        return []
    
    try:
        # Search for Google Docs files
        query = "mimeType='application/vnd.google-apps.document'"
        results = drive_service.files().list(
            q=query,
            pageSize=100,
            fields="nextPageToken, files(id, name, createdTime, modifiedTime)"
        ).execute()
        
        documents = []
        items = results.get('files', [])
        
        for item in items:
            # Get document content for metadata extraction
            content = get_document_content(item['id'])
            student_name = extract_student_name(item['name'])
            lesson_date = extract_lesson_date(content) if content else None
            
            doc_info = {
                'id': item['id'],
                'name': item['name'],
                'student_name': student_name,
                'lesson_date': lesson_date,
                'created_time': item.get('createdTime'),
                'modified_time': item.get('modifiedTime'),
                'token_count': count_tokens(content) if content else 0
            }
            documents.append(doc_info)
        
        # Sort by modified time (most recent first)
        documents.sort(key=lambda x: x['modified_time'], reverse=True)
        
        logger.info(f"Retrieved {len(documents)} documents")
        return documents
        
    except Exception as e:
        logger.error(f"Error getting documents: {e}")
        return []

def filter_by_weekday(documents: List[Dict[str, Any]], weekday: str) -> List[Dict[str, Any]]:
    """Filter documents by weekday"""
    if not weekday:
        return documents
    
    weekday_lower = weekday.lower()
    filtered = []
    
    for doc in documents:
        # Check if weekday is in the document name
        if weekday_lower in doc['name'].lower():
            filtered.append(doc)
        # Check if weekday is in the lesson date
        elif doc['lesson_date']:
            try:
                date_obj = datetime.strptime(doc['lesson_date'], '%Y-%m-%d')
                doc_weekday = date_obj.strftime('%A').lower()
                if weekday_lower in doc_weekday:
                    filtered.append(doc)
            except:
                continue
    
    return filtered

def get_recent_documents(days: int = 30) -> List[Dict[str, Any]]:
    """Get documents modified in the last N days"""
    documents = get_all_documents()
    cutoff_date = datetime.now() - timedelta(days=days)
    
    recent_docs = []
    for doc in documents:
        if doc['modified_time']:
            try:
                modified_date = parser.parse(doc['modified_time'])
                if modified_date.replace(tzinfo=None) >= cutoff_date:
                    recent_docs.append(doc)
            except:
                continue
    
    return recent_docs

# API Routes
@app.route('/')
def home():
    """API root endpoint"""
    return jsonify({
        "name": "GPT Google Docs Proxy",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "docs": {
                "list_all": "/docs/all",
                "read": "/docs/read?file_id=ID",
                "recent": "/docs/recent",
                "batch": "/docs/batch"
            },
            "search": "/search"
        }
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})

@app.route('/docs/all')
def list_all_docs():
    """List all documents with metadata"""
    try:
        limit = request.args.get('limit', type=int)
        weekday = request.args.get('weekday', type=str)
        
        documents = get_all_documents()
        
        # Filter by weekday if specified
        if weekday:
            documents = filter_by_weekday(documents, weekday)
        
        # Apply limit if specified
        if limit and limit > 0:
            documents = documents[:limit]
        
        return jsonify({
            "documents": documents,
            "total": len(documents)
        })
        
    except Exception as e:
        logger.error(f"Error in list_all_docs: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route('/docs/recent')
def list_recent_docs():
    """List recently modified documents"""
    try:
        days = request.args.get('days', default=30, type=int)
        limit = request.args.get('limit', type=int)
        weekday = request.args.get('weekday', type=str)
        
        documents = get_recent_documents(days)
        
        # Filter by weekday if specified
        if weekday:
            documents = filter_by_weekday(documents, weekday)
        
        # Apply limit if specified
        if limit and limit > 0:
            documents = documents[:limit]
        
        return jsonify({
            "documents": documents,
            "total": len(documents),
            "days": days
        })
        
    except Exception as e:
        logger.error(f"Error in list_recent_docs: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route('/docs/read')
def read_document():
    """Read a specific document by ID"""
    try:
        file_id = request.args.get('file_id')
        if not file_id:
            return jsonify({"detail": "file_id parameter is required"}), 400
        
        content = get_document_content(file_id)
        if content is None:
            return jsonify({"detail": "Document not found or error reading document"}), 404
        
        # Get document metadata
        initialize_google_services()
        if drive_service:
            try:
                file_info = drive_service.files().get(fileId=file_id, fields='name,createdTime,modifiedTime').execute()
                student_name = extract_student_name(file_info['name'])
                lesson_date = extract_lesson_date(content)
                
                return jsonify({
                    "file_id": file_id,
                    "name": file_info['name'],
                    "student_name": student_name,
                    "lesson_date": lesson_date,
                    "content": content,
                    "token_count": count_tokens(content),
                    "created_time": file_info.get('createdTime'),
                    "modified_time": file_info.get('modifiedTime')
                })
            except Exception as e:
                logger.error(f"Error getting file metadata: {e}")
                return jsonify({
                    "file_id": file_id,
                    "content": content,
                    "token_count": count_tokens(content)
                })
        else:
            return jsonify({
                "file_id": file_id,
                "content": content,
                "token_count": count_tokens(content)
            })
        
    except Exception as e:
        logger.error(f"Error in read_document: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route('/docs/batch', methods=['POST'])
def batch_read_documents():
    """Read multiple documents by IDs"""
    try:
        data = request.get_json()
        if not data or 'file_ids' not in data:
            return jsonify({"detail": "file_ids list is required in request body"}), 400
        
        file_ids = data['file_ids']
        if not isinstance(file_ids, list):
            return jsonify({"detail": "file_ids must be a list"}), 400
        
        documents = []
        for file_id in file_ids:
            content = get_document_content(file_id)
            if content:
                # Get document metadata
                initialize_google_services()
                if drive_service:
                    try:
                        file_info = drive_service.files().get(fileId=file_id, fields='name,createdTime,modifiedTime').execute()
                        student_name = extract_student_name(file_info['name'])
                        lesson_date = extract_lesson_date(content)
                        
                        documents.append({
                            "file_id": file_id,
                            "name": file_info['name'],
                            "student_name": student_name,
                            "lesson_date": lesson_date,
                            "content": content,
                            "token_count": count_tokens(content),
                            "created_time": file_info.get('createdTime'),
                            "modified_time": file_info.get('modifiedTime')
                        })
                    except Exception as e:
                        logger.error(f"Error getting metadata for {file_id}: {e}")
                        documents.append({
                            "file_id": file_id,
                            "content": content,
                            "token_count": count_tokens(content),
                            "error": f"Metadata error: {str(e)}"
                        })
                else:
                    documents.append({
                        "file_id": file_id,
                        "content": content,
                        "token_count": count_tokens(content)
                    })
        
        return jsonify({
            "documents": documents,
            "total": len(documents)
        })
        
    except Exception as e:
        logger.error(f"Error in batch_read_documents: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route('/search', methods=['POST'])
def search_documents():
    """Search documents using semantic search"""
    try:
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"detail": "query is required in request body"}), 400
        
        query = data['query']
        limit = data.get('limit', 10)
        weekday = data.get('weekday')
        
        if not openai_client:
            return jsonify({"detail": "OpenAI API key not configured"}), 500
        
        # Get all documents
        documents = get_all_documents()
        
        # Filter by weekday if specified
        if weekday:
            documents = filter_by_weekday(documents, weekday)
        
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
        results = []
        for doc in documents:
            content = get_document_content(doc['id'])
            if not content:
                continue
            
            try:
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
                
                results.append({
                    "document": doc,
                    "similarity": float(similarity),
                    "content": content
                })
                
            except Exception as e:
                logger.error(f"Error processing document {doc['id']}: {e}")
                continue
        
        # Sort by similarity and apply limit
        results.sort(key=lambda x: x['similarity'], reverse=True)
        results = results[:limit]
        
        return jsonify({
            "query": query,
            "results": results,
            "total": len(results)
        })
        
    except Exception as e:
        logger.error(f"Error in search_documents: {e}")
        return jsonify({"detail": f"Error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
