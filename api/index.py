import json
import os
import sqlite3
import urllib.parse
import urllib.request
import base64
import time
from http.server import BaseHTTPRequestHandler

# ─── Config ──────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
WA_DB = '/tmp/wa_msgstore.db'

# Dayanna DB: misma base completa, descargada desde B2 a /tmp en Vercel
DAYANNA_DB = '/tmp/dayanna_msgstore.db'
B2_KEY_ID = "0057353d5e43c79000000000c"
B2_APP_KEY = "K005+yQ5tTyFQ4D6v35+s5It5aKh9C4"
B2_BUCKET = "copiashw"
B2_DB_PATH = "vercel-db/dayanna_msgstore.db"
B2_MEDIA_PREFIX = "dayanna/WhatsApp crudo/com.whatsapp/WhatsApp/"

cached_b2 = {"token": None, "download_url": None, "expires": 0}

# ─── B2 Auth ─────────────────────────────────────────────
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

def ensure_dayanna_db():
    if os.path.exists(DAYANNA_DB):
        return True
    try:
        token, dl_url = get_b2_token()
        if not token:
            return False
        req = urllib.request.Request(
            f"{dl_url}/file/{B2_BUCKET}/{B2_DB_PATH}",
            headers={'Authorization': token}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            os.makedirs(os.path.dirname(DAYANNA_DB), exist_ok=True)
            with open(DAYANNA_DB, 'wb') as f:
                f.write(r.read())
        return True
    except Exception as e:
        return False

# ─── Handler ─────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        # ── Serve static HTML files ──
        if path == '/' or path == '':
            self.serve_static('index.html')
            return
        if path == '/dayanna':
            self.serve_static('dayanna.html')
            return
        if path.endswith('.html') or path.endswith('.css') or path.endswith('.js') or path.endswith('.json'):
            static_file = path.lstrip('/')
            if os.path.exists(static_file):
                self.serve_static(static_file)
                return

        # ── General API ──
        if path == '/api/chats':
            data = self.get_chats()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif path == '/api/messages':
            chat_id = params.get('jid', [None])[0]
            limit = int(params.get('limit', [50])[0])
            offset = int(params.get('offset', [0])[0])
            self.send_json(self.get_messages(chat_id, limit, offset))
        elif path == '/api/search':
            q = params.get('q', [''])[0]
            self.send_json(self.search_messages(q))
        elif path == '/api/stats':
            self.send_json(self.get_stats())
        # ── Dayanna API ──
        elif path == '/api/dayanna/chats':
            self.send_json(self.get_dayanna_chats())
        elif path == '/api/dayanna/messages':
            chat_id = params.get('jid', [None])[0]
            limit = int(params.get('limit', [50])[0])
            offset = int(params.get('offset', [0])[0])
            self.send_json(self.get_dayanna_messages(chat_id, limit, offset))
        elif path == '/api/dayanna/media':
            file_path = params.get('path', [None])[0]
            self.serve_b2_media(file_path)
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def serve_static(self, filename):
        """Serve a static HTML file from the project root"""
        root = os.path.dirname(os.path.dirname(__file__))
        filepath = os.path.join(root, filename)
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_json({'error': 'File not found'}, 404)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    # ── General DB ──
    def get_wa_db(self):
        # Descargar la DB completa desde B2 si no está en caché
        if not os.path.exists(WA_DB):
            try:
                token, dl_url = get_b2_token()
                if token:
                    req = urllib.request.Request(
                        f"{dl_url}/file/{B2_BUCKET}/{B2_DB_PATH}",
                        headers={'Authorization': token}
                    )
                    with urllib.request.urlopen(req, timeout=120) as r:
                        os.makedirs(os.path.dirname(WA_DB), exist_ok=True)
                        with open(WA_DB, 'wb') as f:
                            f.write(r.read())
            except:
                pass
        if not os.path.exists(WA_DB):
            return None
        conn = sqlite3.connect(WA_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def get_chats(self):
        conn = self.get_wa_db()
        if not conn:
            return {'chats': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT 
                    j.raw_string,
                    c.subject,
                    c.archived,
                    coalesce(
                        case when j.server = 's.whatsapp.net' then j.user else null end,
                        case when j_pn.server = 's.whatsapp.net' then j_pn.user else null end,
                        ''
                    ) as phone_number,
                    (
                        SELECT coalesce(
                            case when m.text_data != '' then m.text_data else null end,
                            mm.media_caption,
                            case 
                                when m.message_type = 1 then '\\ud83d\\udcf7 Foto'
                                when m.message_type = 2 then '\\ud83c\\udfb5 Audio'
                                when m.message_type = 3 then '\\ud83c\\udfa5 Video'
                                when m.message_type = 20 then '\\ud83c\\udf1f Sticker'
                                when m.message_type = 7 then '\\u2139\\ufe0f Evento del sistema'
                                else '\\ud83d\\udcce Archivo adjunto'
                            end
                        )
                        FROM message m
                        LEFT JOIN message_media mm ON m._id = mm.message_row_id
                        WHERE m.chat_row_id = c._id AND m.message_type != 7
                        ORDER BY m._id DESC LIMIT 1
                    ) as last_msg,
                    datetime(c.sort_timestamp/1000, 'unixepoch', 'localtime') as last_time
                FROM chat c
                JOIN jid j ON c.jid_row_id = j._id
                LEFT JOIN jid_map jm ON jm.lid_row_id = j._id
                LEFT JOIN jid j_pn ON jm.jid_row_id = j_pn._id
                WHERE (c.last_message_row_id > 0 OR c.sort_timestamp > 0)
                ORDER BY c.sort_timestamp DESC
                LIMIT 100
            """)
            chats = []
            for r in cursor.fetchall():
                jid_str = r[0]
                subject = r[1]
                archived = bool(r[2])
                phone = r[3]
                last_msg = r[4]
                last_time = r[5]
                is_grp = '@g.us' in jid_str
                name = subject or (('+' + phone) if phone else jid_str.split('@')[0])
                time_str = ''
                if last_time:
                    time_str = last_time.split(' ')[0][5:]
                chats.append({
                    'jid': jid_str,
                    'name': name,
                    'phone': ('+' + phone) if phone else '',
                    'archived': archived,
                    'is_group': is_grp,
                    'last_msg': last_msg,
                    'time': time_str
                })
            return chats
        except Exception as e:
            return []
        finally:
            conn.close()

    def get_messages(self, chat_id, limit=50, offset=0):
        if not chat_id:
            return {'messages': [], 'error': 'No jid provided'}
        conn = self.get_wa_db()
        if not conn:
            return {'messages': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT 
                    m._id,
                    m.from_me, 
                    m.text_data,
                    mm.media_caption,
                    datetime(m.timestamp/1000, 'unixepoch', 'localtime') as time,
                    mm.file_path,
                    mm.mime_type,
                    m.message_type,
                    mm.media_name,
                    ms.action_type
                FROM message m
                JOIN chat c ON m.chat_row_id = c._id
                JOIN jid j ON c.jid_row_id = j._id
                LEFT JOIN message_media mm ON m._id = mm.message_row_id
                LEFT JOIN message_system ms ON m._id = ms.message_row_id
                WHERE j.raw_string = ?
                ORDER BY m._id ASC
            """, (chat_id,))
            msgs = []
            for r in cursor.fetchall():
                from_me = bool(r[1])
                text_data = r[2]
                caption = r[3]
                time_str = r[4] or ''
                if len(time_str) >= 16:
                    time_str = time_str[11:16]
                file_path = r[5]
                mime = r[6] or ''
                m_type = r[7]
                media_name = r[8]
                action_type = r[9]

                if m_type == 7:
                    text_sys = 'Las llamadas y mensajes en este chat estan cifrados de extremo a extremo.'
                    if action_type == 11:
                        text_sys = 'Se creo el grupo o se actualizo la informacion.'
                    elif action_type == 67:
                        text_sys = 'Tu codigo de seguridad con este contacto cambio.'
                    msgs.append({
                        'type': 'system',
                        'text': text_sys,
                        'time': time_str
                    })
                    continue

                text = caption if caption else text_data
                media_url = None
                media_type = None

                if file_path:
                    media_url = '/media/' + file_path
                    if 'image' in mime or m_type == 1:
                        media_type = 'image'
                    elif 'video' in mime or m_type == 3:
                        media_type = 'video'
                    elif 'audio' in mime or m_type == 2:
                        media_type = 'audio'
                    elif m_type == 20 or 'webp' in mime:
                        media_type = 'sticker'
                    else:
                        media_type = 'file'

                if not text and not media_url:
                    continue

                msgs.append({
                    'type': 'chat',
                    'from_me': from_me,
                    'text': text or '',
                    'time': time_str,
                    'media_url': media_url,
                    'media_type': media_type,
                    'file_name': media_name
                })
            return {'messages': msgs}
        except Exception as e:
            return {'messages': [], 'error': str(e)}
        finally:
            conn.close()

    def search_messages(self, q):
        if not q:
            return {'messages': []}
        conn = self.get_wa_db()
        if not conn:
            return {'messages': [], 'error': 'DB not found'}
        try:
            cursor = conn.execute("""
                SELECT m.text_data, m.from_me,
                    datetime(m.timestamp/1000, 'unixepoch', 'localtime') as time
                FROM message m
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
        conn = self.get_wa_db()
        if not conn:
            return {'stats': {}, 'error': 'DB not found'}
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM message").fetchone()['c']
            chats = conn.execute("SELECT COUNT(*) as c FROM chat").fetchone()['c']
            return {'stats': {'total_messages': total, 'total_chats': chats}}
        except Exception as e:
            return {'stats': {}, 'error': str(e)}
        finally:
            conn.close()

    # ── Dayanna DB (desde B2) ──
    def get_dayanna_db(self):
        if not ensure_dayanna_db():
            return None
        conn = sqlite3.connect(DAYANNA_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def get_dayanna_chats(self):
        conn = self.get_dayanna_db()
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

    def get_dayanna_messages(self, chat_id, limit=50, offset=0):
        conn = self.get_dayanna_db()
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

    def serve_b2_media(self, file_path):
        if not file_path:
            self.send_json({'error': 'No path'}, 404)
            return
        token, dl_url = get_b2_token()
        if not token:
            self.send_response(500)
            self.end_headers()
            return
        b2_path = f"{B2_MEDIA_PREFIX}{file_path}"
        try:
            req = urllib.request.Request(
                f"{dl_url}/file/{B2_BUCKET}/{b2_path}",
                headers={'Authorization': token}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                self.send_response(200)
                self.send_header('Content-Type', r.headers.get('Content-Type', 'image/jpeg'))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.wfile.write(r.read())
        except Exception as e:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
