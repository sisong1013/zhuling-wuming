"""Step 4.2：赛后复盘（名场面时间线）服务端数据。"""

from __future__ import annotations

import pytest

from helpers import (
    assign_cards,
    card_board,
    close_all,
    collect_assigned,
    full_room,
    persona_room,
    start_game,
    submit_all_cards,
    wait_phase,
)

HIGHLIGHT_KEYS = {"opening", "timeout", "sharp", "self_reveal", "longest"}


async def _real_win(ws_base, names, config=None):
    clients = await full_room(ws_base, names, config=config)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "PHASE1", 1, timeout=10)
    return clients


async def test_real_over_has_timeline_and_stats(ws_base):
    """REAL：game:over 带 timeline（时间线）与 stats（统计）。"""
    clients = await _real_win(ws_base, ["甲", "乙", "丙"])
    try:
        # 甲问 2 号（猜一个别人的编号），然后提交正确看板
        target_no = [c.my_room_no for c in clients if c is not clients[0]][0]
        await clients[0].send("phase1:ask", targetRoomNo=target_no, text="你昨晚在哪里？")
        for c in clients[1:]:
            await c.send("phase1:skip")
        await wait_phase(clients[0], "PHASE2", 1, timeout=15)

        # 被问者作答（超时会另测）
        for c in clients[1:]:
            try:
                q = await c.wait_for("question:received", timeout=8)
                await c.send("phase2:answer", questionId=q["questionId"], text="在灯下。")
            except Exception:
                pass

        board = {str(c.my_room_no): c.name for c in clients}
        await clients[0].send("phase1:submit", board=board) if False else None
        # 第一幕早已过去，这里等第二轮再提交
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=30)
        await clients[0].send("phase1:submit", board=board)

        over = await clients[0].wait_for("game:over", timeout=20)
        assert over["timeline"], "时间线不能为空"
        first = over["timeline"][0]
        assert set(first) >= {
            "questionId",
            "round",
            "askerNickname",
            "targetNo",
            "question",
            "answer",
            "status",
            "highlights",
            "highlightLabels",
        }
        assert all(h in HIGHLIGHT_KEYS for h in first["highlights"])
        assert over["stats"]["rounds"] >= 1
        assert over["stats"]["questions"] >= 1
        assert over["stats"]["players"] == 3
    finally:
        await close_all(clients)


async def test_timeout_question_is_highlighted(ws_base):
    """超时的问答要打 timeout 高亮。"""
    clients = await full_room(
        ws_base, ["甲", "乙"], config={"phase1Seconds": 20, "phase2Seconds": 1}
    )
    try:
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)
        target_no = clients[1].my_room_no
        await clients[0].send("phase1:ask", targetRoomNo=target_no, text="怎么不说话？")
        await clients[1].send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=15)

        # 谁都不答，等超时 → 第三幕 → 第二轮
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=15)
            await c.send("phase3:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=30)

        board = {str(c.my_room_no): c.name for c in clients}
        await clients[0].send("phase1:submit", board=board)
        over = await clients[0].wait_for("game:over", timeout=20)

        timed_out = [i for i in over["timeline"] if i["timedOut"]]
        assert timed_out, "应该有超时记录"
        assert "timeout" in timed_out[0]["highlights"]
        assert "超时未答" in timed_out[0]["highlightLabels"]
        assert over["stats"]["timedOut"] >= 1
    finally:
        await close_all(clients)


async def test_self_reveal_highlight_in_persona(ws_base):
    """回答里出现自己的卡名 → 打 self_reveal（自曝身份）高亮。"""
    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        await submit_all_cards(clients)
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await collect_assigned(clients)
        for c in clients:
            await c.send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=15)

        asker, target = clients[0], clients[1]
        await asker.send("phase1:ask", targetRoomNo=target.my_room_no, text="你是谁？")
        got = await target.wait_for("question:received", timeout=10)
        await target.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=15)

        # 故意自曝：把拿到的卡名念出来
        own = target.assigned_card["name"]
        await target.send("phase2:answer", questionId=got["questionId"], text=f"我就是{own}。")
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=20)
            await c.send("phase3:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=30)

        board = card_board(clients)
        await asker.send("phase1:submit", board=board)
        over = await asker.wait_for("game:over", timeout=20)

        flagged = [i for i in over["timeline"] if "self_reveal" in i["highlights"]]
        assert flagged, f"没标记自曝：{[(i['answer'], i['highlights']) for i in over['timeline']]}"
        assert "自曝身份" in flagged[0]["highlightLabels"]
    finally:
        await close_all(clients)


async def test_sharp_question_highlight_for_winner(ws_base):
    """胜者问对人并最终猜中 → sharp（神准提问）。"""
    clients = await full_room(ws_base, ["甲", "乙", "丙"])
    try:
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        victim = clients[2]
        await clients[0].send("phase1:ask", targetRoomNo=victim.my_room_no, text="你怕黑吗？")
        await clients[1].send("phase1:skip")
        await victim.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=20)
            try:
                q = await c.wait_for("question:received", timeout=6)
                await c.send("phase2:answer", questionId=q["questionId"], text="不怕。")
            except Exception:
                pass
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=25)
            await c.send("phase3:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=30)

        board = {str(c.my_room_no): c.name for c in clients}
        await clients[0].send("phase1:submit", board=board)
        over = await clients[0].wait_for("game:over", timeout=20)

        sharp = [i for i in over["timeline"] if "sharp" in i["highlights"]]
        assert sharp, "胜者问对的那一题应该标记为神准提问"
        assert sharp[0]["askerNickname"] == "甲"
        assert "神准提问" in sharp[0]["highlightLabels"]
    finally:
        await close_all(clients)
