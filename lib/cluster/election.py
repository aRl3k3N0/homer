"""
Primary election via advisory lock.

Any node may run the election loop. At any moment, at most one node
holds the lock `primary:election`. That node is primary. Others are
workers or read-only.

Lease is renewed every `heartbeat_seconds`. If a primary dies, its
lease expires after `lease_seconds`, and the next candidate acquires
the lock and promotes itself.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from lib.db import BaseDB


_log = logging.getLogger("homer.cluster.election")

LOCK_NAME = "primary:election"


class Election:
    """
    Advisory-lock-based election.

    Usage:
        el = Election(db, node_id, lease_seconds=30, heartbeat_seconds=10)
        el.on_promote = lambda: node_registry.set_role("primary")
        el.on_demote = lambda: node_registry.set_role("worker")
        el.start()
    """

    def __init__(self, db: BaseDB, node_id: str,
                 lease_seconds: int = 30,
                 heartbeat_seconds: int = 10,
                 on_promote=None, on_demote=None):
        self.db = db
        self.node_id = node_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = max(1, heartbeat_seconds)
        self.on_promote = on_promote
        self.on_demote = on_demote

        self._is_primary = False
        self._token = uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def is_primary(self) -> bool:
        with self._lock:
            return self._is_primary

    # ─────────── Start / stop ───────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="homer-election", daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        # Best-effort release
        try:
            self._release()
        except Exception:
            pass

    # ─────────── Loop ───────────

    def _loop(self):
        # First attempt immediately
        self._attempt()
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self._attempt()
            except Exception as e:
                _log.warning("election loop error: %s", e)

    def _attempt(self):
        with self._lock:
            if self._is_primary:
                # Renew
                ok = self._renew()
                if ok:
                    return
                # Lost the lease -- demote
                self._is_primary = False
                _log.warning("election: lost primary lease, demoting")
                if self.on_demote:
                    try:
                        self.on_demote()
                    except Exception:
                        pass

            # Try to acquire
            ok = self._acquire()
            if ok:
                self._is_primary = True
                _log.info("election: acquired primary lock")
                if self.on_promote:
                    try:
                        self.on_promote()
                    except Exception:
                        pass

    # ─────────── Lock ops ───────────

    def _acquire(self) -> bool:
        now = datetime.now()
        expires = now + timedelta(seconds=self.lease_seconds)
        driver = self.db.driver_name

        try:
            if driver == "sqlite":
                # Single-row upsert where current row is expired or missing
                self.db.execute(
                    "INSERT INTO homer_election "
                    "(name, token, node_id, expires_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "  token = excluded.token, "
                    "  node_id = excluded.node_id, "
                    "  expires_at = excluded.expires_at "
                    "WHERE homer_election.expires_at < ?",
                    [LOCK_NAME, self._token, self.node_id, expires, now],
                )
                self.db.commit()
                return self._owns()

            if driver == "postgres":
                # Atomic upsert with WHERE
                self.db.execute(
                    "INSERT INTO homer_election "
                    "(name, token, node_id, expires_at) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "  token = EXCLUDED.token, "
                    "  node_id = EXCLUDED.node_id, "
                    "  expires_at = EXCLUDED.expires_at "
                    "WHERE homer_election.expires_at < %s",
                    [LOCK_NAME, self._token, self.node_id, expires, now],
                )
                self.db.commit()
                return self._owns()

            # Generic: try UPDATE ... WHERE expired, else INSERT
            row = self.db.fetchone(
                f"SELECT token, expires_at FROM homer_election "
                f"WHERE name = {self._ph(0)}",
                [LOCK_NAME], dictionary=True,
            )
            if row is None:
                self.db.execute(
                    f"INSERT INTO homer_election "
                    f"(name, token, node_id, expires_at) "
                    f"VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, "
                    f"{self._ph(3)})",
                    [LOCK_NAME, self._token, self.node_id, expires],
                )
                self.db.commit()
                return self._owns()

            expires_at = row["expires_at"]
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at)
                except ValueError:
                    expires_at = now
            if expires_at < now:
                self.db.execute(
                    f"UPDATE homer_election SET token = {self._ph(0)}, "
                    f"node_id = {self._ph(1)}, expires_at = {self._ph(2)} "
                    f"WHERE name = {self._ph(3)}",
                    [self._token, self.node_id, expires, LOCK_NAME],
                )
                self.db.commit()
                return self._owns()
            return False
        except Exception as e:
            _log.warning("election acquire error: %s", e)
            return False

    def _renew(self) -> bool:
        expires = datetime.now() + timedelta(seconds=self.lease_seconds)
        try:
            cur = self.db.execute(
                f"UPDATE homer_election SET expires_at = {self._ph(0)} "
                f"WHERE name = {self._ph(1)} AND token = {self._ph(2)}",
                [expires, LOCK_NAME, self._token],
            )
            self.db.commit()
            return cur.rowcount == 1
        except Exception:
            return False

    def _owns(self) -> bool:
        try:
            row = self.db.fetchone(
                f"SELECT token FROM homer_election "
                f"WHERE name = {self._ph(0)}",
                [LOCK_NAME], dictionary=True,
            )
            if not row:
                return False
            token = row["token"] if isinstance(row, dict) else row[0]
            return token == self._token
        except Exception:
            return False

    def _release(self):
        try:
            self.db.execute(
                f"DELETE FROM homer_election "
                f"WHERE name = {self._ph(0)} AND token = {self._ph(1)}",
                [LOCK_NAME, self._token],
            )
            self.db.commit()
        except Exception:
            pass

    def _ph(self, idx: int) -> str:
        style = self.db._placeholder_style
        if style == ":name":
            return f":{idx + 1}"
        if style == "?":
            return "?"
        return "%s"
