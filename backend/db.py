"""Tiny SQLite persistence layer (JSON columns) - no external DB needed for the demo."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

DATA_DIR = os.getenv("LENDSPRINT_DATA", os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "lendsprint.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with _lock, conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, data TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, app_id TEXT, data TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, app_id TEXT, ts TEXT, actor TEXT, action TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, app_id TEXT, ts TEXT, role TEXT, content TEXT);
        """)


# ---- generic JSON-row helpers ------------------------------------------------------
def put(table, id_, data, app_id=None):
    with _lock, conn() as c:
        if table == "documents":
            c.execute("INSERT OR REPLACE INTO documents (id, app_id, data, created) VALUES (?,?,?,COALESCE((SELECT created FROM documents WHERE id=?),?))",
                      (id_, app_id or data.get("app_id"), json.dumps(data), id_, now()))
        else:
            c.execute("INSERT OR REPLACE INTO applications (id, data, created) VALUES (?,?,COALESCE((SELECT created FROM applications WHERE id=?),?))",
                      (id_, json.dumps(data), id_, now()))


def get(table, id_):
    with conn() as c:
        r = c.execute(f"SELECT data FROM {table} WHERE id=?", (id_,)).fetchone()
    return json.loads(r["data"]) if r else None


def update(table, id_, **fields):
    with _lock:
        with conn() as c:
            r = c.execute(f"SELECT data FROM {table} WHERE id=?", (id_,)).fetchone()
            if not r:
                return None
            d = json.loads(r["data"])
            d.update(fields)
            c.execute(f"UPDATE {table} SET data=? WHERE id=?", (json.dumps(d), id_))
    return d


def list_apps():
    with conn() as c:
        rows = c.execute("SELECT data FROM applications ORDER BY created DESC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def list_docs(app_id):
    with conn() as c:
        rows = c.execute("SELECT data FROM documents WHERE app_id=? ORDER BY created", (app_id,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def delete_doc(doc_id):
    with _lock, conn() as c:
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))


# ---- audit & chat --------------------------------------------------------------------
def audit(app_id, actor, action, detail=None):
    with _lock, conn() as c:
        c.execute("INSERT INTO audit (app_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
                  (app_id, now(), actor, action, json.dumps(detail or {})))


def audit_log(app_id):
    with conn() as c:
        rows = c.execute("SELECT ts, actor, action, detail FROM audit WHERE app_id=? ORDER BY id DESC", (app_id,)).fetchall()
    return [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": json.loads(r["detail"])} for r in rows]


def add_chat(app_id, role, content):
    with _lock, conn() as c:
        c.execute("INSERT INTO chats (app_id, ts, role, content) VALUES (?,?,?,?)", (app_id, now(), role, content))


def chat_history(app_id):
    with conn() as c:
        rows = c.execute("SELECT ts, role, content FROM chats WHERE app_id=? ORDER BY id", (app_id,)).fetchall()
    return [dict(r) for r in rows]
