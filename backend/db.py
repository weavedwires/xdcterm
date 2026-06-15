import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "xdcterm.db"
_lock = threading.Lock()


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    with _lock:
        c = _conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                addr TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS messages (
                msg_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                opened_at TEXT NOT NULL DEFAULT (datetime('now')),
                closed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        c.execute("INSERT OR IGNORE INTO config (key, value) SELECT 'admin_id', CAST(MIN(user_id) AS TEXT) FROM users")
        c.commit()
        c.close()


def upsert_user(user_id: int, display_name: str, addr: str) -> None:
    with _lock:
        c = _conn()
        was_empty = c.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"] == 0
        c.execute(
            """INSERT INTO users (user_id, display_name, addr, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   display_name=excluded.display_name,
                   addr=excluded.addr,
                   updated_at=excluded.updated_at""",
            (user_id, display_name, addr),
        )
        if was_empty:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('admin_id', ?)", (str(user_id),))
        c.commit()
        c.close()


def add_message(msg_id: int, user_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO messages (msg_id, user_id) VALUES (?, ?)", (msg_id, user_id))
        c.commit()
        c.close()


def get_user_by_msg(msg_id: int) -> dict | None:
    with _lock:
        c = _conn()
        row = c.execute(
            """SELECT u.* FROM users u
               JOIN messages m ON u.user_id = m.user_id
               WHERE m.msg_id = ?""",
            (msg_id,),
        ).fetchone()
        c.close()
        return dict(row) if row else None


def open_session(msg_id: int, user_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute("INSERT INTO sessions (msg_id, user_id) VALUES (?, ?)", (msg_id, user_id))
        c.commit()
        c.close()


def close_session(msg_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE sessions SET closed_at = datetime('now') WHERE msg_id = ? AND closed_at IS NULL",
            (msg_id,),
        )
        c.commit()
        c.close()


def get_active_sessions() -> list[dict]:
    with _lock:
        c = _conn()
        rows = c.execute(
            """SELECT s.id, s.msg_id, s.opened_at, u.display_name, u.addr
               FROM sessions s
               JOIN users u ON s.user_id = u.user_id
               WHERE s.closed_at IS NULL
               ORDER BY s.opened_at""",
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


def get_admin() -> dict | None:
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT u.* FROM users u JOIN config k ON k.value = CAST(u.user_id AS TEXT) WHERE k.key = 'admin_id'"
        ).fetchone()
        c.close()
        return dict(row) if row else None


def get_admin_message_id() -> int | None:
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT m.msg_id FROM messages m JOIN config k ON k.value = CAST(m.user_id AS TEXT) WHERE k.key = 'admin_id' LIMIT 1"
        ).fetchone()
        c.close()
        return row["msg_id"] if row else None
