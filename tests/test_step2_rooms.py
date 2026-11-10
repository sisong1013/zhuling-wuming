"""Step 2：房间码机制 —— 建房、加入、广播、错误码。"""

from __future__ import annotations

import pytest

from helpers import WsClient, create_room, full_room, join_room


async def test_create_room_gives_6_digit_code(ws_base):
    c = await create_room(ws_base, "队长甲")
    try:
        assert c.room_code is not None
        assert len(c.room_code) == 6, c.room_code
        assert c.room_code.isdigit(), c.room_code
        assert c.is_captain is True
        assert c.player_id
    finally:
        await c.close()


async def test_room_code_is_unique(ws_base):
    codes = set()
    clients = []
    try:
        for i in range(6):
            c = await create_room(ws_base, f"房主{i}")
            clients.append(c)
            codes.add(c.room_code)
        assert len(codes) == 6
    finally:
        for c in clients:
            await c.close()


async def test_three_joins_broadcast_count_four(ws_base):
    captain = await create_room(ws_base, "队长")
    clients = [captain]
    try:
        for nick in ("乙", "丙", "丁"):
            clients.append(await join_room(ws_base, captain.room_code, nick))
        # 最后一条 room:state 应该是 4 人
        for c in clients:
            st = await c.wait_for("room:state", pred=lambda m: m.get("count") == 4, timeout=5)
            nicknames = [p["nickname"] for p in st["players"]]
            assert sorted(nicknames) == sorted(["队长", "乙", "丙", "丁"])
            assert st["onlineCount"] == 4
            assert st["phase"] == "LOBBY"
            assert st["captainId"] == captain.player_id
            # 开局前不该有任何编号信息
            assert all(p.get("roomNo") is None for p in st["players"])
            assert st["you"].get("roomNo") is None
    finally:
        for c in clients:
            await c.close()


async def test_duplicate_nickname_rejected(ws_base):
    captain = await create_room(ws_base, "同名者")
    other = await WsClient.connect(ws_base, "dup")
    try:
        await other.send("room:join", roomCode=captain.room_code, nickname="同名者")
        err = await other.wait_for("room:error", timeout=4)
        assert err["code"] == "NICKNAME_TAKEN"
        assert err["message"]
        # 房间人数没有变化
        st = await captain.wait_for("room:state", timeout=3)
        assert st["count"] == 1
    finally:
        await other.close()
        await captain.close()


async def test_unknown_room_code_rejected(ws_base):
    c = await WsClient.connect(ws_base, "流浪者")
    try:
        await c.send("room:join", roomCode="000000", nickname="流浪者")
        err = await c.wait_for("room:error", timeout=4)
        assert err["code"] == "ROOM_NOT_FOUND"
    finally:
        await c.close()


async def test_join_with_empty_nickname_rejected(ws_base):
    captain = await create_room(ws_base, "房主")
    other = await WsClient.connect(ws_base, "blank")
    try:
        await other.send("room:join", roomCode=captain.room_code, nickname="   ")
        err = await other.wait_for("room:error", timeout=4)
        assert err["code"] == "NICKNAME_INVALID"
    finally:
        await other.close()
        await captain.close()


async def test_join_returns_joined_and_player_id(ws_base):
    captain = await create_room(ws_base, "房主B")
    joiner = await join_room(ws_base, captain.room_code, "小队员")
    try:
        assert joiner.player_id and joiner.player_id != captain.player_id
        assert joiner.is_captain is False
        assert joiner.room_code == captain.room_code
    finally:
        await joiner.close()
        await captain.close()


async def test_disconnect_marks_offline(ws_base):
    captain, joiner = await full_room(ws_base, ["留观者", "要走的人"])
    try:
        await joiner.close()
        st = await captain.wait_for(
            "room:state", pred=lambda m: m.get("onlineCount") == 1 and m.get("count") == 2, timeout=6
        )
        gone = [p for p in st["players"] if p["id"] == joiner.player_id][0]
        assert gone["connected"] is False
    finally:
        await captain.close()


async def test_create_twice_on_same_connection_rejected(ws_base):
    c = await create_room(ws_base, "贪心")
    try:
        await c.send("room:create", nickname="第二间")
        err = await c.wait_for("room:error", timeout=4)
        assert err["code"] == "ALREADY_IN_ROOM"
    finally:
        await c.close()


async def test_captain_can_patch_config(ws_base):
    c = await create_room(ws_base, "配置控")
    try:
        await c.send("setup:config", phase1Seconds=5, forcedSubmitRound=3)
        st = await c.wait_for("room:state", pred=lambda m: m["config"]["phase1Seconds"] == 5, timeout=4)
        assert st["config"]["forcedSubmitRound"] == 3
    finally:
        await c.close()
