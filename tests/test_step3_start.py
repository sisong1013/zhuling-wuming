"""Step 3：开局 —— 只有队长能开始、随机编号、逐人下发、绝不下发映射。"""

from __future__ import annotations

import time

import pytest

from helpers import (
    WsClient,
    assert_no_mapping,
    close_all,
    full_room,
    numbers_to_nicknames,
    start_game,
    wait_phase,
)

NAMES = ["队长", "乙", "丙", "丁"]


async def test_non_captain_cannot_start(ws_base):
    clients = await full_room(ws_base, ["队长甲", "副队乙", "队员丙"])
    try:
        await clients[1].send("game:start")
        err = await clients[1].wait_for("error", timeout=4)
        assert err["code"] == "NOT_CAPTAIN"
        # 阶段不应变化：队长在窗口内收不到 phase:changed
        msgs = await clients[0].collect(0.5)
        assert all(m.get("type") != "phase:changed" for m in msgs), msgs
    finally:
        await close_all(clients)


async def test_second_start_rejected(ws_base):
    clients = await full_room(ws_base, NAMES)
    try:
        await start_game(clients)
        await clients[0].send("game:start")
        err = await clients[0].wait_for("error", timeout=4)
        assert err["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_start_needs_two_players(ws_base):
    c = await full_room(ws_base, ["孤单的人"])
    try:
        await c[0].send("game:start")
        err = await c[0].wait_for("error", timeout=4)
        assert err["code"] == "NOT_ENOUGH_PLAYERS"
    finally:
        await close_all(c)


async def test_start_assigns_unique_numbers_in_range(ws_base):
    clients = await full_room(ws_base, NAMES)
    try:
        await start_game(clients)
        nos = [c.my_room_no for c in clients]
        assert len(set(nos)) == 4, nos
        assert set(nos) == {1, 2, 3, 4}, nos
        for c in clients:
            # 编号数组是升序全量，和昵称数组没有位置对应关系（防止顺序泄露映射）
            assert c.room_nos == [1, 2, 3, 4]
            assert sorted(c.nicknames) == sorted(NAMES)
    finally:
        await close_all(clients)


async def test_phase_changed_to_phase1_with_deadline(ws_base):
    clients = await full_room(ws_base, NAMES)
    try:
        await start_game(clients)
        msg = await wait_phase(clients[0], "PHASE1", 1)
        assert msg["round"] == 1
        # 服务端权威计时：只广播 deadline 时间戳
        assert msg["deadline"] > time.time() + 50
        assert msg["deadline"] <= time.time() + 61
        assert msg["forcedSubmit"] is False
    finally:
        await close_all(clients)


async def test_no_mapping_ever_sent(ws_base):
    clients = await full_room(ws_base, NAMES)
    try:
        await start_game(clients)
        # 等所有人进入 PHASE1，再收集全部消息做泄露扫描
        for c in clients:
            await wait_phase(c, "PHASE1", 1)
        await clients[0].collect(0.3)

        god = numbers_to_nicknames(clients)  # 上帝视角（只在测试进程里拼出来）
        assert sorted(god) == [1, 2, 3, 4]

        for c in clients:
            msgs = await c.collect(0.3)
            assert_no_mapping(msgs, 4)
            for m in msgs:
                if m.get("type") == "game:started":
                    assert m["yourRoomNo"] == c.my_room_no
                    assert set(m.keys()) == {
                        "type",
                        "roomCode",
                        "yourRoomNo",
                        "roomNos",
                        "nicknames",
                        "round",
                        "config",
                    }
                if m.get("type") == "room:state":
                    # 别人的编号永远不出现
                    for p in m["players"]:
                        assert "roomNo" not in p or p["roomNo"] is None
                    assert m["you"]["roomNo"] == c.my_room_no
    finally:
        await close_all(clients)


async def test_random_numbers_differ_between_rooms(ws_base):
    """两个房间各开一局，编号分配应各自独立随机（这里只断言合法性，不断言顺序）。"""
    a = await full_room(ws_base, ["a1", "a2", "a3", "a4"])
    b = await full_room(ws_base, ["b1", "b2", "b3", "b4"])
    try:
        await start_game(a)
        await start_game(b)
        for group in (a, b):
            assert sorted(c.my_room_no for c in group) == [1, 2, 3, 4]
    finally:
        await close_all(a + b)
