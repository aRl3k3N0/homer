"""
Tests for advisory lock context manager.
"""
import threading
import time

import pytest


@pytest.fixture
def db(cluster_config):
    from lib.db import connect
    conn = connect("sqlite",
                   {"path": cluster_config.get("scheduler.sqlite.path")})
    conn.execute("""
        CREATE TABLE IF NOT EXISTS homer_advisory_locks (
            name VARCHAR(255) PRIMARY KEY,
            token VARCHAR(64) NOT NULL,
            locked_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )
    """)
    conn.commit()
    yield conn
    conn.close()


def test_advisory_lock_acquire_and_release(db):
    from lib.cluster.advisory import advisory_lock

    with advisory_lock(db, "test", ttl_seconds=5) as ok:
        assert ok
        row = db.fetchone(
            "SELECT 1 FROM homer_advisory_locks WHERE name = ?",
            ["test"],
        )
        assert row is not None

    # After exit -- row removed
    row = db.fetchone(
        "SELECT 1 FROM homer_advisory_locks WHERE name = ?",
        ["test"],
    )
    assert row is None


def test_advisory_lock_blocks_second_holder(db):
    from lib.cluster.advisory import advisory_lock

    order = []

    def worker_a():
        with advisory_lock(db, "shared", ttl_seconds=2) as ok:
            if ok:
                order.append("A")
                time.sleep(1.5)

    def worker_b():
        time.sleep(0.2)
        with advisory_lock(db, "shared", ttl_seconds=2) as ok:
            order.append(("B", ok))

    ta = threading.Thread(target=worker_a)
    tb = threading.Thread(target=worker_b)
    ta.start(); tb.start()
    ta.join(); tb.join()

    assert order[0] == "A"
    assert order[1] == ("B", False)


def test_advisory_lock_expires(db):
    from lib.cluster.advisory import advisory_lock
    from datetime import datetime, timedelta

    # Simulate a stale lock
    db.execute(
        "INSERT INTO homer_advisory_locks "
        "(name, token, locked_at, expires_at) VALUES (?, ?, ?, ?)",
        ["stale", "old-token",
         datetime.now() - timedelta(seconds=60),
         datetime.now() - timedelta(seconds=30)],
    )
    db.commit()

    with advisory_lock(db, "stale", ttl_seconds=5) as ok:
        assert ok, "Expired lock should be reacquirable"
