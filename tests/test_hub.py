"""Fan-out to open pages: ordering, dropping, and giving up on a slow one."""

from __future__ import annotations

import asyncio
import json

from kcgx.hub import LOG_SIZE, Client, Hub, zulu


def sink(size=64):
    sent = []

    async def send(text):
        sent.append(json.loads(text))

    evictions = []
    client = Client(send, on_evict=lambda: evictions.append(True), size=size)
    return client, sent, evictions


def queued(client):
    out = []
    while not client.queue.empty():
        out.append(json.loads(client.queue.get_nowait()))
    return out


async def test_a_broadcast_reaches_every_page_in_order():
    hub = Hub()
    a, _, _ = sink()
    b, _, _ = sink()
    hub.add(a)
    hub.add(b)
    hub.broadcast({"t": "one"})
    hub.broadcast({"t": "two"})
    assert [f["t"] for f in queued(a)] == ["one", "two"]
    assert [f["t"] for f in queued(b)] == ["one", "two"]


async def test_the_pump_sends_what_was_queued():
    hub = Hub()
    client, sent, _ = sink()
    hub.add(client)
    hub.broadcast({"t": "one"})
    task = asyncio.create_task(client.pump())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    assert sent == [{"t": "one"}]


async def test_a_send_that_fails_ends_the_pump_quietly():
    async def broken(text):
        raise ConnectionError("socket gone")

    client = Client(broken)
    client.offer("{}")
    await asyncio.wait_for(client.pump(), 1)  # returns rather than raising


async def test_a_full_page_skips_a_level_frame_and_stays():
    hub = Hub()
    client, _, evictions = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "levels"}, droppable=True)
    assert client in hub.clients
    assert evictions == []
    assert [f["t"] for f in queued(client)] == ["feed"]


async def test_a_full_page_is_dropped_rather_than_sent_a_gap():
    """A page that misses a feed or order frame is out of step for good;
    reconnecting gets it a snapshot, which is the only honest repair."""
    hub = Hub()
    client, _, evictions = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "order"})
    assert client not in hub.clients
    assert evictions == [True]


async def test_a_slow_page_does_not_hold_up_the_others():
    hub = Hub()
    slow, _, _ = sink(size=1)
    fast, _, _ = sink()
    hub.add(slow)
    hub.add(fast)
    for n in range(5):
        hub.broadcast({"t": "feed", "n": n})
    assert [f["n"] for f in queued(fast)] == [0, 1, 2, 3, 4]


async def test_an_evicted_page_is_sent_nothing_more():
    hub = Hub()
    client, _, _ = sink(size=1)
    hub.add(client)
    hub.broadcast({"t": "feed"})
    hub.broadcast({"t": "feed"})
    queued(client)
    hub.broadcast({"t": "feed"})
    assert queued(client) == []


async def test_a_removed_page_is_sent_nothing():
    hub = Hub()
    client, _, _ = sink()
    hub.add(client)
    hub.remove(client)
    hub.broadcast({"t": "feed"})
    assert queued(client) == []


async def test_a_note_is_logged_stamped_in_zulu_and_shown():
    hub = Hub(clock=lambda: 1792371300.0)  # 2026-10-19 00:55 UTC
    client, _, _ = sink()
    hub.add(client)
    entry = hub.note("TROUTDALE TOWER: reconnecting")
    assert entry == {"z": "0055Z", "text": "TROUTDALE TOWER: reconnecting"}
    assert list(hub.log) == [entry]
    assert queued(client) == [{"t": "message", **entry}]


async def test_the_log_is_capped():
    hub = Hub()
    for n in range(LOG_SIZE + 5):
        hub.note(str(n))
    assert len(hub.log) == LOG_SIZE
    assert hub.log[0]["text"] == "5"


def test_zulu_is_hours_and_minutes_utc():
    assert zulu(0) == "0000Z"
    assert zulu(19 * 3600 + 55 * 60) == "1955Z"


# -- the boot animation (phase G decision 1) -----------------------------------


async def test_only_the_first_page_a_hub_welcomes_is_told_to_boot():
    """Once per launch: the first page the server serves after it starts
    plays the boot animation; every later one, a reconnect included, does not."""
    hub = Hub()
    first, _, _ = sink()
    second, _, _ = sink()
    hub.welcome(first, {"t": "snapshot", "boot": False})
    hub.welcome(second, {"t": "snapshot"})
    hub.remove(first)
    again, _, _ = sink()  # the first page, reconnected
    hub.welcome(again, {"t": "snapshot"})
    assert [queued(c)[0]["boot"] for c in (first, second, again)] == [True, False, False]


async def test_a_welcome_queues_the_snapshot_first_then_joins():
    hub = Hub()
    client, _, _ = sink()
    hub.welcome(client, {"t": "snapshot"})
    hub.broadcast({"t": "feed"})
    assert client in hub.clients
    assert [f["t"] for f in queued(client)] == ["snapshot", "feed"]


async def test_a_welcome_does_not_change_the_snapshot_it_is_given():
    hub = Hub()
    client, _, _ = sink()
    frame = {"t": "snapshot", "boot": False}
    hub.welcome(client, frame)
    assert frame == {"t": "snapshot", "boot": False}
