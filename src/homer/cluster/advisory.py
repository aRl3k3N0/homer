# lib/cluster/advisory.py

from contextlib import contextmanager
from datetime import datetime, timedelta
import uuid


@contextmanager
def advisory_lock(db, name: str, ttl_seconds: int = 60):
    """
    Acquire a named lock. Yields True if acquired, False if not.
    """
    if db.driver_name == "postgres":
        # Use Postgres native advisory lock, non-blocking
        row = db.fetchone(
            "SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", [name],
            dictionary=True,
        )
        ok = row and (row["ok"] if isinstance(row, dict) else row[0])
        try:
            yield ok
        finally:
            if ok:
                db.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))", [name],
                )
                db.commit()
        return

    # Generic fallback via table
    token = uuid.uuid4().hex
    now = datetime.now()
    expires = now + timedelta(seconds=ttl_seconds)
    try:
        db.execute(
            "INSERT INTO homer_advisory_locks "
            "(name, token, locked_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            [name, token, now, expires],
        )
        db.commit()
        acquired = True
    except Exception:
        # Someone else holds it; check expiry
        row = db.fetchone(
            "SELECT token, expires_at FROM homer_advisory_locks WHERE name = ?",
            [name], dictionary=True,
        )
        if row and isinstance(row, dict):
            expires_at = row["expires_at"]
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at)
                except ValueError:
                    expires_at = now
            if expires_at < now:
                db.execute(
                    "UPDATE homer_advisory_locks SET token = ?, "
                    "locked_at = ?, expires_at = ? WHERE name = ?",
                    [token, now, expires, name],
                )
                db.commit()
                acquired = True
            else:
                acquired = False
        else:
            acquired = False

    try:
        yield acquired
    finally:
        if acquired:
            try:
                db.execute(
                    "DELETE FROM homer_advisory_locks "
                    "WHERE name = ? AND token = ?",
                    [name, token],
                )
                db.commit()
            except Exception:
                pass
