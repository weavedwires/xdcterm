import sqlite3
import threading
from pathlib import Path

from models import User

DB_PATH = Path(__file__).parent / "data" / "xdcterm.db"


class Database:
    def __init__(self):
        self._lock = threading.Lock()
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init(self):
        with self._lock:
            c = self._get_conn()
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

    def upsert_user(self, user_id: int, display_name: str, addr: str) -> User:
        with self._lock:
            c = self._get_conn()
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
            return User(user_id, display_name, addr)

    def add_message(self, msg_id: int, user_id: int) -> None:
        with self._lock:
            self._get_conn().execute(
                "INSERT OR IGNORE INTO messages (msg_id, user_id) VALUES (?, ?)",
                (msg_id, user_id),
            )
            self._get_conn().commit()

    def get_user_by_msg(self, msg_id: int) -> User | None:
        with self._lock:
            row = self._get_conn().execute(
                """SELECT u.* FROM users u
                   JOIN messages m ON u.user_id = m.user_id
                   WHERE m.msg_id = ?""",
                (msg_id,),
            ).fetchone()
            return User(**row) if row else None

    def open_session(self, msg_id: int, user_id: int) -> None:
        with self._lock:
            self._get_conn().execute(
                "INSERT INTO sessions (msg_id, user_id) VALUES (?, ?)",
                (msg_id, user_id),
            )
            self._get_conn().commit()

    def close_session(self, msg_id: int) -> None:
        with self._lock:
            self._get_conn().execute(
                "UPDATE sessions SET closed_at = datetime('now') WHERE msg_id = ? AND closed_at IS NULL",
                (msg_id,),
            )
            self._get_conn().commit()

    def get_active_sessions(self) -> list[dict]:
        with self._lock:
            rows = self._get_conn().execute(
                """SELECT s.id, s.msg_id, s.opened_at, u.display_name, u.addr
                   FROM sessions s
                   JOIN users u ON s.user_id = u.user_id
                   WHERE s.closed_at IS NULL
                   ORDER BY s.opened_at""",
            ).fetchall()
            return [dict(r) for r in rows]

    def get_admin_message_id(self) -> int | None:
        with self._lock:
            row = self._get_conn().execute(
                "SELECT m.msg_id FROM messages m JOIN config k ON k.value = CAST(m.user_id AS TEXT) WHERE k.key = 'admin_id' LIMIT 1"
            ).fetchone()
            return row["msg_id"] if row else None


db = Database()
