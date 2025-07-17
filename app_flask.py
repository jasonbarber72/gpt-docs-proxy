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
SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly"
]

# Initialize Google API credentials
docs_service = None
drive_service = None

def initialize_google_services():
    """Initialize Google API services - called on first use"""
    global docs_service, drive_service
    
    if docs_service is not None:
        return
    
    try:
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES
            )
        else:
            # Try to load from environment variable (for Render deployment)
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if service_account_json:
                try:
                    service_account_info = json.loads(service_account_json)
                    creds = service_account.Credentials.from_service_account_info(
                        service_account_info, scopes=SCOPES
                    )
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON")
                    return
            else:
                logger.error("No Google service account credentials found")
                return
        
        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)
        logger.info("Google API services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Google API: {e}")
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

def get_document_text(file_id: str, max_paragraphs: int = None, stop_at_date: str = None) -> str:
    """Get text content from Google Doc, optionally limiting to first few paragraphs or stopping at a date"""
    initialize_google_services()
    if not docs_service:
        raise Exception("Google Docs service not available")
    
    try:
        # Check cache first
        cache_key = f"{file_id}_{max_paragraphs or 'full'}_{stop_at_date or 'no_date'}"
        if cache_key in doc_cache:
            return doc_cache[cache_key]['text']
        
        doc = docs_service.documents().get(documentId=file_id).execute()
        text_parts = []
        paragraph_count = 0
        
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            
            # If we have a paragraph limit and we've reached it, stop
            if max_paragraphs and paragraph_count >= max_paragraphs:
                break
            
            paragraph_text = ""
            for run in paragraph.get("elements", []):
                text_run = run.get("textRun")
                if text_run and text_run.get("content"):
                    paragraph_text += text_run["content"]
            
            if paragraph_text.strip():  # Only count non-empty paragraphs
                text_parts.append(paragraph_text)
                paragraph_count += 1
                
                # If we have a stop date and we've hit it, stop reading
                if stop_at_date and stop_at_date in paragraph_text:
                    break
        
        partial_text = "".join(text_parts)
        
        # Cache the result
        doc_cache[cache_key] = {
            'text': partial_text,
            'name': doc.get("title", ""),
            'cached_at': datetime.now(),
            'is_partial': max_paragraphs is not None or stop_at_date is not None
        }
        
        return partial_text
    except Exception as e:
        logger.error(f"Error reading document {file_id}: {e}")
        raise Exception(f"Google Docs error: {e}")

def get_recent_lessons_from_doc(file_id: str, days_back: int = 7) -> str:
    """Get recent lessons from a document, stopping when we hit older dates in headings"""
    # Calculate the cutoff date
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    # Common date formats in your documents
    date_formats = [
        "%a %d %b %y",  # "Thu 3 Jul 25"
        "%A %d %B %Y",  # "Thursday 3 July 2025"  
        "%d %b %y",     # "3 Jul 25"
        "%d/%m/%y",     # "3/7/25"
        "%d/%m/%Y",     # "3/7/2025"
        "%Y-%m-%d",     # "2025-07-03"
    ]
    
    def parse_date_from_heading(heading_text: str) -> Optional[datetime]:
        """Try to parse a date from a heading"""
        for fmt in date_formats:
            try:
                return datetime.strptime(heading_text.strip(), fmt)
            except ValueError:
                continue
        return None
    
    initialize_google_services()
    if not docs_service:
        raise Exception("Google Docs service not available")
    
    try:
        doc = docs_service.documents().get(documentId=file_id).execute()
        recent_content = []
        
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            
            # Extract paragraph text
            paragraph_text = ""
            for run in paragraph.get("elements", []):
                text_run = run.get("textRun")
                if text_run and text_run.get("content"):
                    paragraph_text += text_run["content"]
            
            # Check if this is a heading (check for heading style)
            is_heading = False
            paragraph_style = paragraph.get("paragraphStyle", {})
            named_style_type = paragraph_style.get("namedStyleType", "")
            
            if "HEADING" in named_style_type:
                is_heading = True
                # Try to parse date from heading
                parsed_date = parse_date_from_heading(paragraph_text)
                if parsed_date and parsed_date < cutoff_date:
                    # We've hit an old date, stop reading
                    logger.info(f"Stopping at date: {parsed_date} (cutoff: {cutoff_date})")
                    break
            
            if paragraph_text.strip():
                recent_content.append(paragraph_text)
        
        return "".join(recent_content)
    except Exception as e:
        logger.error(f"Error reading recent lessons from document {file_id}: {e}")
        raise Exception(f"Google Docs error: {e}")

def create_embedding(text: str) -> List[float]:
    """Create embedding for text using OpenAI"""
    if not openai_client:
        raise Exception("OpenAI client not initialized")
    
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"OpenAI embedding error: {e}")
        raise Exception(f"OpenAI error: {e}")

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    a_array = np.array(a)
    b_array = np.array(b)
    return np.dot(a_array, b_array) / (np.linalg.norm(a_array) * np.linalg.norm(b_array))

@app.route("/", methods=["GET"])
def index():
    """Root endpoint with API documentation"""
    return {
        "name": "GPT Google Docs Proxy",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "docs": {
                "list_all": "/docs/all",
                "read": "/docs/read?file_id=ID",
                "batch": "/docs/batch",
                "recent": "/docs/recent"
            },
            "search": "/search"
        }
    }

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return {"status": "ok"}

@app.route("/docs/all", methods=["GET"])
def list_all_docs():
    """List all Google Docs metadata"""
    initialize_google_services()
    if not drive_service:
        return {"detail": "Google Drive service not available"}, 500
    
    try:
        # Get limit from query parameter
        limit = request.args.get('limit', type=int)
        
        # Search for Google Docs
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document'",
            fields="files(id, name)",
            pageSize=limit or 1000
        ).execute()
        
        items = results.get("files", [])
        
        # Return basic info without token counts for speed
        docs_list = []
        for item in items:
            docs_list.append({
                "id": item["id"],
                "name": item["name"],
                "token_count": 0  # Will be calculated on-demand
            })
        
        return docs_list
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        return {"detail": f"Error: {str(e)}"}, 500

@app.route("/docs/read", methods=["GET"])
def read_doc_by_id():
    """Get full text of a doc by file_id"""
    file_id = request.args.get('file_id')
    max_paragraphs = request.args.get('max_paragraphs', type=int)
    
    if not file_id:
        return {"detail": "file_id parameter required"}, 400
    
    try:
        text = get_document_text(file_id, max_paragraphs=max_paragraphs)
        return {
            "id": file_id,
            "text": text,
            "char_count": len(text),
            "token_count": count_tokens(text)
        }
    except Exception as e:
        logger.error(f"Error reading document {file_id}: {e}")
        return {"detail": f"Error: {str(e)}"}, 500

@app.route("/docs/batch", methods=["POST"])
def batch_read_docs():
    """Get multiple docs by IDs"""
    data = request.get_json()
    doc_ids = data.get('doc_ids', [])
    
    if not doc_ids:
        return {"detail": "doc_ids required"}, 400
    
    results = []
    for doc_id in doc_ids:
        try:
            text = get_document_text(doc_id)
            results.append({
                "id": doc_id,
                "text": text,
                "char_count": len(text),
                "token_count": count_tokens(text)
            })
        except Exception as e:
            logger.error(f"Error reading document {doc_id}: {e}")
            results.append({
                "id": doc_id,
                "error": str(e)
            })
    
    return results

@app.route("/docs/recent", methods=["GET"])
def get_recent_lessons():
    """Get recent lessons from documents, stopping at older dates in headings"""
    student = request.args.get('student')
    weekday = request.args.get('weekday')
    days_back = request.args.get('days_back', default=7, type=int)
    
    initialize_google_services()
    if not drive_service:
        return {"detail": "Google Drive service not available"}, 500
    
    try:
        # Get all documents
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document'",
            fields="files(id, name)",
            pageSize=1000
        ).execute()
        
        items = results.get("files", [])
        recent_lessons = []
        
        for item in items:
            # Filter by student if specified
            if student and student.lower() not in item["name"].lower():
                continue
            
            # Filter by weekday if specified
            if weekday and weekday.lower() not in item["name"].lower():
                continue
            
            try:
                recent_text = get_recent_lessons_from_doc(item["id"], days_back=days_back)
                if recent_text.strip():
                    recent_lessons.append({
                        "id": item["id"],
                        "name": item["name"],
                        "recent_content": recent_text,
                        "token_count": count_tokens(recent_text)
                    })
            except Exception as e:
                logger.warning(f"Could not get recent lessons from {item['name']}: {e}")
        
        return recent_lessons
    except Exception as e:
        logger.error(f"Error getting recent lessons: {e}")
        return {"detail": f"Error: {str(e)}"}, 500

@app.route("/search", methods=["POST"])
def search():
    """Search within docs using embeddings"""
    data = request.get_json()
    query = data.get('query', '')
    student = data.get('student', 'any')
    n = data.get('n', 5)
    
    if not query:
        return {"detail": "query required"}, 400
    
    if not openai_client:
        return {"detail": "OpenAI client not available"}, 500
    
    initialize_google_services()
    if not drive_service:
        return {"detail": "Google Drive service not available"}, 500
    
    try:
        # Create embedding for the query
        query_embedding = create_embedding(query)
        
        # Get all documents
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.document'",
            fields="files(id, name)",
            pageSize=1000
        ).execute()
        
        items = results.get("files", [])
        search_results = []
        
        for item in items:
            # Filter by student if specified
            if student != 'any' and student.lower() not in item["name"].lower():
                continue
            
            try:
                # Get document text (recent content only)
                text = get_recent_lessons_from_doc(item["id"], days_back=14)
                if not text.strip():
                    continue
                
                # Create embedding for document
                doc_embedding = create_embedding(text)
                
                # Calculate similarity
                similarity = cosine_similarity(query_embedding, doc_embedding)
                
                # Extract excerpt (first 500 chars)
                excerpt = text[:500] + ("..." if len(text) > 500 else "")
                
                search_results.append({
                    "id": item["id"],
                    "name": item["name"],
                    "excerpt": excerpt,
                    "token_count": count_tokens(excerpt),
                    "similarity": similarity
                })
            except Exception as e:
                logger.warning(f"Could not search document {item['name']}: {e}")
        
        # Sort by similarity and return top n
        search_results.sort(key=lambda x: x['similarity'], reverse=True)
        return search_results[:n]
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return {"detail": f"Error: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
