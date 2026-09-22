import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger("memory")


def utc():
    return datetime.now(timezone.utc).isoformat()


class Memory:
    def __init__(self, path, world_id):
        self.world = world_id
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY, world TEXT NOT NULL, category TEXT NOT NULL,
            subject TEXT NOT NULL, text TEXT NOT NULL, confidence REAL NOT NULL,
            source TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(world,category,subject,text));
          CREATE INDEX IF NOT EXISTS memory_scope ON memories(world,category,updated_at);
          CREATE TABLE IF NOT EXISTS goals (
            world TEXT NOT NULL, goal_id TEXT NOT NULL, description TEXT NOT NULL,
            status TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(world,goal_id));
          CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY, world TEXT NOT NULL, session TEXT NOT NULL,
            event_id INTEGER NOT NULL, received_at TEXT NOT NULL, event_json TEXT NOT NULL,
            UNIQUE(world,session,event_id));
          CREATE TABLE IF NOT EXISTS runtime (world TEXT NOT NULL, key TEXT NOT NULL,
            value TEXT NOT NULL, PRIMARY KEY(world,key));
          PRAGMA user_version=1;
        """)

    def close(self):
        with self.lock:
            self.db.close()

    def remember(self, category, subject, text, confidence, source):
        now = utc()
        with self.lock, self.db:
            self.db.execute("""INSERT INTO memories(world,category,subject,text,confidence,source,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(world,category,subject,text) DO UPDATE SET
                confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at""",
                (self.world, category, subject, text, confidence, source, now, now))
        LOG.info("memory write category=%s subject_length=%d", category, len(subject))
        return {"ok": True}

    def recall(self, query="", category=None, limit=15):
        # Literal substring search; parameterized SQL; names cannot inject SQL.
        with self.lock:
            rows = self.db.execute("""SELECT * FROM memories WHERE world=?
                AND (? IS NULL OR category=?) AND (instr(lower(subject),lower(?))>0 OR instr(lower(text),lower(?))>0)
                ORDER BY updated_at DESC,id DESC LIMIT ?""", (self.world, category, category, query, query, limit)).fetchall()
        return [dict(row) for row in rows]

    def goal(self, goal_id, description, status, source):
        with self.lock, self.db:
            self.db.execute("""INSERT INTO goals VALUES(?,?,?,?,?,?) ON CONFLICT(world,goal_id) DO UPDATE SET
              description=excluded.description,status=excluded.status,source=excluded.source,updated_at=excluded.updated_at""",
              (self.world, goal_id, description, status, source, utc()))
        LOG.info("goal updated status=%s", status)
        return {"ok": True}

    def goals(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM goals WHERE world=? AND status IN ('active','deferred') ORDER BY updated_at DESC LIMIT 30", (self.world,))]

    def add_chat(self, session, event, retention_days):
        with self.lock, self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO conversations(world,session,event_id,received_at,event_json) VALUES(?,?,?,?,?)",
                (self.world, session, event["event_id"], utc(), json.dumps(event, ensure_ascii=False)))
            added = cur.rowcount != 0
        self.prune_conversations(retention_days)
        return added

    def prune_conversations(self, retention_days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self.lock, self.db:
            self.db.execute("DELETE FROM conversations WHERE received_at < ?", (cutoff,))
            self.db.execute("DELETE FROM conversations WHERE world=? AND id NOT IN (SELECT id FROM conversations WHERE world=? ORDER BY id DESC LIMIT 2000)", (self.world, self.world))

    def conversation(self, limit=40):
        with self.lock:
            rows = self.db.execute("SELECT session,event_json FROM conversations WHERE world=? ORDER BY id DESC LIMIT ?", (self.world, limit)).fetchall()
        return [dict(json.loads(r["event_json"]), session_id=r["session"]) for r in reversed(rows)]

    def state(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM runtime WHERE world=? AND key=?", (self.world, key)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT INTO runtime VALUES(?,?,?) ON CONFLICT(world,key) DO UPDATE SET value=excluded.value", (self.world,key,json.dumps(value)))

    def call(self, name, a):
        if name == "remember_fact":
            return self.remember(a["category"], a["subject"], a["text"], a["confidence"], a["source"])
        if name == "remember_location":
            return self.remember("locations", a["name"], a["description"], a["confidence"], a["source"])
        if name == "recall":
            return self.recall(a["query"], limit=a.get("limit", 15))
        if name == "find_location":
            return self.recall(a.get("query", ""), "locations")
        if name == "recent_events":
            return self.recall(category="events", limit=a.get("limit", 15))
        if name == "get_relationship":
            # Exact stable-ID matching, never substring trust matching.
            with self.lock:
                rows = self.db.execute("SELECT * FROM memories WHERE world=? AND subject=? AND category IN ('people','relationships') ORDER BY updated_at DESC LIMIT 30", (self.world,a["player_id"])).fetchall()
            return [dict(r) for r in rows]
        if name == "update_goal":
            return self.goal(**a)
        raise ValueError("Unknown memory tool")
