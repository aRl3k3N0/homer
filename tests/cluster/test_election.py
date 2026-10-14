"""
Tests for advisory-lock based election.
"""
import threading
import time


def test_election_acquires_lock(cluster_config):
    from lib.db import connect
    from lib.cluster.election import Election

    db = connect("sqlite",
                 {"path": cluster_config.get("scheduler.sqlite.path")})

    # Create the election table
    db.execute("""
        CREATE TABLE IF NOT EXISTS homer_election (
            name VARCHAR(255) PRIMARY KEY,
            token VARCHAR(64) NOT NULL,
            node_id VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )
    """)
    db.commit()

    promoted = threading.Event()

    el = Election(
        db=db,
        node_id="node-a",
        lease_seconds=5,
        heartbeat_seconds=1,
        on_promote=lambda: promoted.set(),
    )
    el.start()
    assert promoted.wait(timeout=3), "Node A was not promoted"
    assert el.is_primary

    el.stop()


def test_election_prevents_double_primary(cluster_config):
    from lib.db import connect
    from lib.cluster.election import Election

    db_path = cluster_config.get("scheduler.sqlite.path")
    db1 = connect("sqlite", {"path": db_path})
    db2 = connect("sqlite", {"path": db_path})

    for db in (db1, db2):
        db.execute("""
            CREATE TABLE IF NOT EXISTS homer_election (
                name VARCHAR(255) PRIMARY KEY,
                token VARCHAR(64) NOT NULL,
                node_id VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        db.commit()

    a_won = threading.Event()
    b_won = threading.Event()

    el_a = Election(db=db1, node_id="A", lease_seconds=10,
                    heartbeat_seconds=1,
                    on_promote=lambda: a_won.set())
    el_b = Election(db=db2, node_id="B", lease_seconds=10,
                    heartbeat_seconds=1,
                    on_promote=lambda: b_won.set())

    el_a.start()
    el_b.start()

    time.sleep(2)

    primaries = [el_a.is_primary, el_b.is_primary]
    assert sum(primaries) <= 1, "Both nodes became primary!"

    el_a.stop()
    el_b.stop()


def test_election_promotes_after_lease_expires(cluster_config):
    from lib.db import connect
    from lib.cluster.election import Election

    db_path = cluster_config.get("scheduler.sqlite.path")
    db1 = connect("sqlite", {"path": db_path})
    db2 = connect("sqlite", {"path": db_path})

    for db in (db1, db2):
        db.execute("""
            CREATE TABLE IF NOT EXISTS homer_election (
                name VARCHAR(255) PRIMARY KEY,
                token VARCHAR(64) NOT NULL,
                node_id VARCHAR(64) NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        db.commit()

    el_a = Election(db=db1, node_id="A", lease_seconds=2,
                    heartbeat_seconds=1)
    el_a.start()
    time.sleep(1)
    assert el_a.is_primary

    # Kill A (simulate crash: no stop, no release)
    el_a._is_primary = False  # avoid release on stop
    try:
        el_a.stop()
    except Exception:
        pass

    b_promoted = threading.Event()
    el_b = Election(db=db2, node_id="B", lease_seconds=5,
                    heartbeat_seconds=1,
                    on_promote=lambda: b_promoted.set())
    el_b.start()

    # B should be promoted after A's lease expires (~2s)
    assert b_promoted.wait(timeout=10)
    el_b.stop()
