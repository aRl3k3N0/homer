"""
Tests for NodeRegistry: register, heartbeat, list, purge, commands.
"""
from datetime import datetime, timedelta


def test_register_and_list(registry):
    registry.register()
    nodes = registry.list_nodes(only_alive=False)
    assert any(n.id == registry.node_id for n in nodes)
    me = next(n for n in nodes if n.id == registry.node_id)
    assert me.role == "worker"
    assert me.version == "1.0.0"


def test_register_is_idempotent(registry):
    registry.register()
    registry.register()
    nodes = registry.list_nodes(only_alive=False)
    ids = [n.id for n in nodes]
    assert ids.count(registry.node_id) == 1


def test_heartbeat_updates_last_seen(registry):
    registry.register()
    n1 = next(n for n in registry.list_nodes(only_alive=False)
              if n.id == registry.node_id)
    registry._heartbeat()
    n2 = next(n for n in registry.list_nodes(only_alive=False)
              if n.id == registry.node_id)
    assert n2.last_seen >= n1.last_seen


def test_list_only_alive_filters_dead(registry):
    registry.register()
    # Force last_seen to be far in the past
    old = datetime.now() - timedelta(seconds=600)
    registry.db.execute(
        f"UPDATE homer_nodes SET last_seen = {registry._ph(0)} "
        f"WHERE id = {registry._ph(1)}",
        [old, registry.node_id],
    )
    registry.db.commit()

    alive = registry.list_nodes(only_alive=True)
    assert all(n.id != registry.node_id for n in alive)

    all_nodes = registry.list_nodes(only_alive=False)
    assert any(n.id == registry.node_id for n in all_nodes)


def test_purge_dead_removes_old_nodes(registry):
    registry.register()
    old = datetime.now() - timedelta(seconds=3600)
    registry.db.execute(
        f"UPDATE homer_nodes SET last_seen = {registry._ph(0)} "
        f"WHERE id = {registry._ph(1)}",
        [old, registry.node_id],
    )
    registry.db.commit()

    n = registry.purge_dead()
    assert n >= 1
    remaining = registry.list_nodes(only_alive=False)
    assert all(x.id != registry.node_id for x in remaining)


def test_unregister(registry):
    registry.register()
    assert any(n.id == registry.node_id
               for n in registry.list_nodes(only_alive=False))
    registry.unregister()
    assert all(n.id != registry.node_id
               for n in registry.list_nodes(only_alive=False))


def test_publish_and_poll_commands(registry):
    registry.register()
    # Manually publish a shutdown command
    registry.db.execute(
        f"INSERT INTO homer_node_commands "
        f"(node_id, action, payload, created_at) "
        f"VALUES ({registry._ph(0)}, {registry._ph(1)}, "
        f"{registry._ph(2)}, {registry._ph(3)})",
        [registry.node_id, "shutdown", "{}", datetime.now()],
    )
    registry.db.commit()

    cmds = registry.poll_commands()
    assert len(cmds) == 1
    assert cmds[0]["action"] == "shutdown"

    # Polling again returns nothing (picked_at is set)
    cmds2 = registry.poll_commands()
    assert cmds2 == []


def test_handle_command_shutdown_sets_stop(registry):
    registry.register()
    registry._handle_command({"id": 1, "action": "shutdown", "payload": {}})
    assert registry._stop.is_set()


def test_handle_command_set_role(registry):
    registry.register()
    registry._handle_command({
        "id": 1, "action": "set-role", "payload": {"role": "primary"},
    })
    assert registry.role == "primary"
