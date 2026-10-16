"""
Tests for the cluster WebSocket hub (ChangeHub) with backpressure.
"""
import asyncio
import json

import pytest

from homer.cluster.ws_server import ChangeHub, get_hub


class FakeWS:
    def __init__(self, fail_after: int = 10**9, delay: float = 0.0):
        self.sent = []
        self.accepted = False
        self.closed = False
        self.close_code = None
        self._fail_after = fail_after
        self._delay = delay

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        if self._delay:
            await asyncio.sleep(self._delay)
        if len(self.sent) >= self._fail_after:
            raise RuntimeError("send failed")
        self.sent.append(text)

    async def close(self, code=None, reason=None):
        self.closed = True
        self.close_code = code


@pytest.mark.asyncio
async def test_subscribe_and_broadcast():
    hub = ChangeHub()
    ws = FakeWS()
    await hub.subscribe(ws)
    assert ws.accepted
    assert hub.count == 1

    await hub.broadcast({"type": "test", "x": 1})
    # Wait for writer task to consume
    await asyncio.sleep(0.1)
    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["type"] == "test"

    await hub.unsubscribe(ws)
    assert hub.count == 0


@pytest.mark.asyncio
async def test_broadcast_is_non_blocking_when_slow():
    """
    A slow subscriber must not block broadcast to others.
    """
    hub = ChangeHub()
    slow = FakeWS(delay=0.5)     # each send takes 0.5s
    fast = FakeWS()
    await hub.subscribe(slow)
    await hub.subscribe(fast)

    # Burst 50 messages; the slow queue (maxsize 100) will fill eventually
    for i in range(50):
        await hub.broadcast({"n": i})

    # Wait briefly
    await asyncio.sleep(0.2)
    # Fast subscriber should have processed messages already
    assert len(fast.sent) >= 10

    await hub.unsubscribe(slow)
    await hub.unsubscribe(fast)


@pytest.mark.asyncio
async def test_backpressure_drops_slow_subscriber():
    hub = ChangeHub()
    slow = FakeWS(delay=10.0)   # effectively hangs
    await hub.subscribe(slow)

    # Burst more than queue maxsize
    for i in range(150):
        await hub.broadcast({"n": i})

    # Give hub time to hit overflow
    await asyncio.sleep(0.2)
    # slow must have been closed and removed
    assert hub.count == 0 or slow.closed


def test_get_hub_is_singleton():
    a = get_hub()
    b = get_hub()
    assert a is b
