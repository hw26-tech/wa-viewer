import json
import os
import sqlite3
import urllib.parse
import urllib.request
import base64
import time
from http.server import BaseHTTPRequestHandler

# En Vercel solo podemos escribir en /tmp
# Descargamos la DB desde B2 si no está en caché local
DB_PATH = '/tmp/dayanna_msgstore.db'
B2_KEY_ID = "0057353d5e43c79000000000c"
B2_APP_KEY = "K005+yQ5tTyFQ4D6v35+s5It5aKh9C4"
B2_BUCKET_NAME = "copiashw"
B2_DB_PATH = "vercel-db/dayanna_msgstore.db"
B2_PREFIX = "dayanna/WhatsApp crudo/com.whatsapp/WhatsApp/"

cached_b2 = {"token": None, "download_url": None, "expires": 0}

def get_b2_token():
    now = time.time()
    if cached_b2["token"] and now < cached_b2["expires"]:
        return cached_b2["token"], cached_b2["download_url"]
    try:
        auth = base64.b64encode(f"{B2_KEY_ID}:{B2_APP_KEY}".encode()).decode()
        req = urllib.request.Request(
            'https://api.backblazeb2.com/b2api/v3/b2_authorize_account',
            headers={'Authorization': f'Basic {auth}'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            cached_b2["token"] = data["authorizationToken"]
            cached_b2["download_url"] = data["downloadUrl"]
            cached_b2["expires"] = now + 3600
            return cached_b2["token"], cached_b2["download_url"]
    except Exception as e:
        return None, None

def ensure_db():
    """Descarga la DB desde B2 si no está en /tmp"""
    if os.path.exists(DB_PATH):
        return True
    try:
        token, dl_url = get_b2_token()
        if not token:
            return False
        req = urllib.request.Request(
            f"{dl_url}/file/{B2_BUCKET_NAME}/{B2_DB_PATH}",
            headers={'Authorization': token}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            with open(DB_PATH, 'wb') as f:
                f.write(r.read())
        return True
    except Exception as e:
        return False

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        
        if path == '/api/dayanna/chats':
            self.send_json(self.get_chats())
        elif path == '/api/dayanna/messages':
            chat_id = params.get('jid', [None])[0]
            limit = int(params.get('limit', [50])[0])
            offset = int(params.get('offset', [0])[0])
            self.send_json(self.get_messages(chat_id, limit, offset))
        elif path == '/api/dayanna/media':
            file_path = params.get('path', [None])[0]
            self.serve_b2_media(file_path)
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def get_db(self):
        if not ensure_db():
            return None
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_chats(self):
        conn = self.get_db()
        if not conn:
            return {'chats': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT jid, subject, created_timestamp, sort_timestamp
                FROM chat_list
                ORDER BY sort_timestamp DESC
                LIMIT 50
            """)
            return {'chats': [dict(row) for row in cursor.fetchall()]}
        except Exception as e:
            return {'chats': [], 'error': str(e)}
        finally:
            conn.close()
    
    def get_messages(self, chat_id, limit=50, offset=0):
        conn = self.get_db()
        if not conn:
            return {'messages': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT m.message_id, m.text_data, m.timestamp, m.from_me, m.media_type, m.file_path
                FROM messages m
                WHERE m.chat_id = ?
                ORDER BY m.timestamp DESC
                LIMIT ? OFFSET ?
            """, (chat_id, limit, offset))
            return {'messages': [dict(row) for row in cursor.fetchall()]}
        except Exception as e:
            return {'messages': [], 'error': str(e)}
        finally:
            conn.close()
    
    def get_b2_media_token(self):
        return get_b2_token()
    
    def serve_b2_media(self, file_path):
        token, dl_url = self.get_b2_media_token()
        if not token:
            self.send_response(500)
            self.end_headers()
            return
        b2_path = f"{B2_PREFIX}{file_path}"
        try:
            req = urllib.request.Request(
                f"{dl_url}/file/{B2_BUCKET_NAME}/{b2_path}",
                headers={'Authorization': token}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                self.send_response(200)
                self.send_header('Content-Type', r.headers.get('Content-Type', 'image/jpeg'))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.write(r.read())
        except Exception as e:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
