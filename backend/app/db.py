import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- owner | employee | ai_agent
    salary_account TEXT,                -- staff salary account (spots self-payment)
    email TEXT UNIQUE,                  -- login (demo accounts)
    password_hash TEXT,                 -- PBKDF2-SHA256, never the plain password
    paused INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    bank_account TEXT NOT NULL, bank_name TEXT,
    verified_email TEXT NOT NULL, verified_phone TEXT,
    created_at TEXT NOT NULL, created_by TEXT,
    bank_changed_at TEXT, bank_changed_by TEXT,
    bank_change_source TEXT,            -- verified_contact | email:<address>
    previous_account TEXT
);
CREATE TABLE IF NOT EXISTS stock (
    sku TEXT PRIMARY KEY, name TEXT NOT NULL, size TEXT, qty INTEGER NOT NULL, price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT
);
CREATE TABLE IF NOT EXISTS customer_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT, email TEXT, text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new | answered | blocked
    reply TEXT, event_id INTEGER
);
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, to_actor TEXT NOT NULL, ts TEXT NOT NULL,
    from_name TEXT, from_addr TEXT, subject TEXT, body TEXT,
    ask TEXT,                             -- JSON describing what the email asks for
    sent_by_visitor INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor_id TEXT NOT NULL,
    action TEXT NOT NULL, system TEXT, summary TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    score REAL NOT NULL DEFAULT 0, level TEXT NOT NULL DEFAULT 'clear',
    outcome TEXT NOT NULL DEFAULT 'done', -- done | flagged | held | blocked
    reasons TEXT NOT NULL DEFAULT '[]',
    history INTEGER NOT NULL DEFAULT 0    -- 1 = past activity used for the baseline
);
CREATE INDEX IF NOT EXISTS ix_events ON events(actor_id, action, ts);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, supplier_id TEXT NOT NULL,
    amount REAL NOT NULL, bank_account TEXT NOT NULL, prepared_by TEXT NOT NULL,
    reference TEXT,
    status TEXT NOT NULL,                 -- awaiting_owner | held | paid | blocked
    alert_id INTEGER, history INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL, level TEXT NOT NULL, score REAL NOT NULL,
    title TEXT NOT NULL, line TEXT, reasons TEXT NOT NULL, metric TEXT,
    payment_id INTEGER, supplier_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open | checking | cleared | held
    note TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bank_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, amount REAL NOT NULL, reference TEXT, from_name TEXT
);
"""

JSON_COLS = ("params", "reasons", "metric", "ask")


class DB:
    """Tiny thread-safe wrapper around one sqlite connection."""

    def __init__(self, path=None):
        path = path or os.environ.get("SHAMAR_DB", "shamar.db")
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(actors)")]
        if cols and "password_hash" not in cols:  # old demo database: start again
            for t in ("alerts", "payments", "events", "inbox", "customer_queries", "customers",
                      "stock", "suppliers", "actors", "settings"):
                self.conn.execute(f"DROP TABLE IF EXISTS {t}")
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def q(self, sql, args=()):
        with self.lock:
            return [to_dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def many(self, sql, rows):
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def wipe(self):
        with self.lock:
            for t in ("alerts", "payments", "events", "inbox", "customer_queries",
                      "customers", "stock", "suppliers", "actors", "settings", "bank_deposits"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("DELETE FROM sqlite_sequence")
            self.conn.commit()

    def get(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set(self, key, value):
        self.run("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(value)))


def to_dict(r):
    d = dict(r)
    for k in JSON_COLS:
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d
