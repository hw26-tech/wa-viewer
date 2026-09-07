import json
import os
import sqlite3
import urllib.parse
import base64
import time
from http.server import BaseHTTPRequestHandler

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
WA_DB = os.path.join(DATA_DIR, 'msgstore.db')

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        # Serve static HTML
        if path == '/' or path == '':
            self.serve_static('index.html')
            return
        if path == '/dayanna':
            self.serve_static('dayanna.html')
            return

        # API endpoints
        if path == '/api/chats':
            self.send_json(self.get_chats())
        elif path == '/api/messages':
            chat_id = params.get('jid', [None])[0]
            limit = int(params.get('limit', [50])[0])
            offset = int(params.get('offset', [0])[0])
            self.send_json(self.get_messages(chat_id))
        elif path == '/api/stats':
            self.send_json(self.get_stats())
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def serve_static(self, filename):
        root = os.path.dirname(os.path.dirname(__file__))
        filepath = os.path.join(root, filename)
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f.read())
        else:
            self.send_json({'error': 'File not found'}, 404)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def get_db(self):
        if not os.path.exists(WA_DB):
            return None
        conn = sqlite3.connect(WA_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def get_chats(self):
        conn = self.get_db()
        if not conn:
            return []
        try:
            cursor = conn.execute("""
                SELECT j.raw_string, c.subject, c.archived,
                    coalesce(
                        case when j.server='s.whatsapp.net' then j.user else null end,
                        case when j_pn.server='s.whatsapp.net' then j_pn.user else null end, ''
                    ) as phone_number,
                    datetime(c.sort_timestamp/1000,'unixepoch','localtime') as last_time
                FROM chat c
                JOIN jid j ON c.jid_row_id = j._id
                LEFT JOIN jid_map jm ON jm.lid_row_id = j._id
                LEFT JOIN jid j_pn ON jm.jid_row_id = j_pn._id
                WHERE c.last_message_row_id > 0 OR c.sort_timestamp > 0
                ORDER BY c.sort_timestamp DESC LIMIT 100
            """)
            chats = []
            for r in cursor.fetchall():
                jid_str = r[0]
                name = r[1] or (('+' + r[3]) if r[3] else jid_str.split('@')[0])
                time_str = ''
                if r[4]:
                    time_str = r[4].split(' ')[0][5:]
                chats.append({
                    'jid': jid_str, 'name': name,
                    'phone': ('+' + r[3]) if r[3] else '',
                    'archived': bool(r[2]),
                    'is_group': '@g.us' in jid_str,
                    'time': time_str
                })
            return chats
        except:
            return []
        finally:
            conn.close()

    def get_messages(self, chat_id):
        if not chat_id:
            return {'messages': []}
        conn = self.get_db()
        if not conn:
            return {'messages': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT m.from_me, m.text_data,
                    datetime(m.timestamp/1000,'unixepoch','localtime') as time
                FROM message m
                JOIN chat c ON m.chat_row_id = c._id
                JOIN jid j ON c.jid_row_id = j._id
                WHERE j.raw_string = ? AND m.message_type != 7
                ORDER BY m._id ASC
            """, (chat_id,))
            msgs = []
            for r in cursor.fetchall():
                msgs.append({
                    'type': 'chat',
                    'from_me': bool(r[0]),
                    'text': r[1] or '',
                    'time': (r[2] or '')[11:16]
                })
            return {'messages': msgs}
        except:
            return {'messages': []}
        finally:
            conn.close()

    def get_stats(self):
        conn = self.get_db()
        if not conn:
            return {'stats': {}}
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM message").fetchone()['c']
            chats = conn.execute("SELECT COUNT(*) as c FROM chat").fetchone()['c']
            return {'stats': {'total_messages': total, 'total_chats': chats}}
        except:
            return {'stats': {}}
        finally:
            conn.close()
