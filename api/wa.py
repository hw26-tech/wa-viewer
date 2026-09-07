import json
import os
import sqlite3
import urllib.parse
import base64
from http.server import BaseHTTPRequestHandler

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'msgstore.db')

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        
        if path == '/api/chats':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = self.get_chats()
            self.wfile.write(json.dumps(data).encode())
        elif path == '/api/messages':
            chat_id = params.get('jid', [None])[0]
            limit = int(params.get('limit', [50])[0])
            offset = int(params.get('offset', [0])[0])
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = self.get_messages(chat_id, limit, offset)
            self.wfile.write(json.dumps(data).encode())
        elif path == '/api/search':
            q = params.get('q', [''])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = self.search_messages(q)
            self.wfile.write(json.dumps(data).encode())
        elif path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = self.get_stats()
            self.wfile.write(json.dumps(data).encode())
        elif path == '/api/media':
            file_path = params.get('path', [None])[0]
            self.serve_media(file_path)
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Not found'}).encode())
    
    def get_db(self):
        if not os.path.exists(DB_PATH):
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
                LIMIT 100
            """)
            chats = [dict(row) for row in cursor.fetchall()]
            return {'chats': chats}
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
            msgs = [dict(row) for row in cursor.fetchall()]
            return {'messages': msgs}
        except Exception as e:
            return {'messages': [], 'error': str(e)}
        finally:
            conn.close()
    
    def search_messages(self, q):
        conn = self.get_db()
        if not conn:
            return {'messages': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT m.message_id, m.text_data, m.timestamp, m.from_me
                FROM messages m
                WHERE m.text_data LIKE ?
                ORDER BY m.timestamp DESC
                LIMIT 50
            """, (f'%{q}%',))
            msgs = [dict(row) for row in cursor.fetchall()]
            return {'messages': msgs}
        except Exception as e:
            return {'messages': [], 'error': str(e)}
        finally:
            conn.close()
    
    def get_stats(self):
        conn = self.get_db()
        if not conn:
            return {'stats': {}, 'error': 'DB not found'}
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()['c']
            chats = conn.execute("SELECT COUNT(*) as c FROM chat_list").fetchone()['c']
            return {'stats': {'total_messages': total, 'total_chats': chats}}
        except Exception as e:
            return {'stats': {}, 'error': str(e)}
        finally:
            conn.close()
    
    def serve_media(self, path):
        if not path:
            self.send_response(404)
            self.end_headers()
            return
        if os.path.exists(path):
            with open(path, 'rb') as f:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
