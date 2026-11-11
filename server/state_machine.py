"""房间注册表 + 状态机（服务端权威）。

所有阶段切换、计时、判定都从这里出发；WebSocket 层只负责解析消息、校验后调用这里。
`GameRegistry.hub` 是发送出口（见 ws_handlers.ConnectionHub），这样本文件不依赖传输细节。
"""

from __future__ import annotations

import logging
import asyncio
import random
import time
from typing import Any, Protocol

from . import ai, ai_agent
from . import rules
from .models import (
    ActionKind,
    GameConfig,
    GameError,
    GameMode,
    PersonaCard,
    Phase,
    Player,
    Question,
    QuestionStatus,
    Room,
    new_id,
)
from .timers import TimerKey, TimerManager

log = logging.getLogger("game.state")


class Hub(Protocol):
    """只需要「给某个玩家发一条消息」这一种能力。"""

    async def send(self, player_id: str, payload: dict[str, Any]) -> bool: ...


class GameRegistry:
    """全部房间的内存注册表。单进程单实例。"""

    def __init__(self, hub: Hub, timers: TimerManager | None = None) -> None:
        self.hub = hub
        self.rooms: dict[str, Room] = {}
        self.sessions: dict[str, Any] = {}  # player_id → Session（心跳用）
        self.ai_log: list[dict[str, Any]] = []  # AI 的 Prompt/决策留痕（/debug/ai）
        self.timers = timers or TimerManager()
        self._player_room: dict[str, str] = {}

    # ==================================================================
    # 房间生命周期
    # ==================================================================
    def create_room(self, nickname: Any) -> tuple[Room, Player]:
        """建房：生成全局唯一 6 位码，创建者为队长。"""
        nick = rules.normalize_nickname(nickname)
        code = rules.generate_room_code(self.rooms.keys())
        room = Room(code=code)
        player = Player(
            id=new_id("p"),
            nickname=nick,
            is_captain=True,
            reconnect_token=new_id("rt"),
        )
        room.captain_id = player.id
        room.players[player.id] = player
        self.rooms[code] = room
        self._player_room[player.id] = code
        log.info("建房 %s by %s", code, nick)
        return room, player

    def join_room(self, room_code: Any, nickname: Any) -> tuple[Room, Player]:
        """加入：校验房间存在 / 未开始 / 昵称唯一 / 人数未满。"""
        nick = rules.normalize_nickname(nickname)
        code = room_code.strip() if isinstance(room_code, str) else ""
        room = self.rooms.get(code)
        if room is None:
            raise GameError("ROOM_NOT_FOUND", "房间码不存在，请核对后重试")
        if room.started_at or room.phase is not Phase.LOBBY:
            raise GameError("ROOM_ALREADY_STARTED", "这局游戏已经开始了，无法加入")
        if room.count >= room.config.max_players:
            raise GameError("ROOM_FULL", f"房间已满（上限 {room.config.max_players} 人）")
        if room.by_nickname(nick) is not None:
            raise GameError("NICKNAME_TAKEN", "这个昵称在房间里已被占用")
        player = Player(id=new_id("p"), nickname=nick, reconnect_token=new_id("rt"))
        room.players[player.id] = player
        self._player_room[player.id] = code
        log.info("加入 %s by %s", code, nick)
        return room, player

    def room_of(self, player_id: str) -> Room | None:
        code = self._player_room.get(player_id)
        return self.rooms.get(code) if code else None

    def player_of(self, player_id: str) -> tuple[Room, Player] | tuple[None, None]:
        room = self.room_of(player_id)
        if room is None:
            return None, None
        player = room.player(player_id)
        if player is None:
            return None, None
        return room, player

    def mark_disconnected(self, player_id: str) -> Room | None:
        """断线：只标 offline（第一周不做断线重连）。"""
        room, player = self.player_of(player_id)
        if room is None or player is None:
            return None
        player.connected = False
        return room

    def mark_connected(self, player_id: str) -> Room | None:
        room, player = self.player_of(player_id)
        if room is None or player is None:
            return None
        player.connected = True
        return room

    # ==================================================================
    # 发送辅助
    # ==================================================================
    async def broadcast_state(self, room: Room) -> None:
        """给每个在线玩家发一份「只含本人编号」的 room:state。"""
        for p in room.ordered_players():
            if not p.connected:
                continue
            await self.hub.send(p.id, room.to_state(p))

    async def broadcast(self, room: Room, payload: dict[str, Any]) -> None:
        """广播同一条消息给全部在线玩家。"""
        for p in room.ordered_players():
            if not p.connected:
                continue
            await self.hub.send(p.id, payload)

    async def broadcast_qa(self, room: Room, builder, q) -> None:
        """问答按观众定制：全公开/半公开/私密 三档都在这里分流。

        builder(room, q, viewer_id) 返回 None 表示「这个人不该看到这条」。
        """
        for viewer in room.ordered_players():
            if not viewer.connected:
                continue
            payload = builder(room, q, viewer.id)
            if payload is None:
                continue
            await self.hub.send(viewer.id, payload)

    async def send_to(self, room: Room, player_id: str, payload: dict[str, Any]) -> None:
        if room.player(player_id) is not None:
            await self.hub.send(player_id, payload)

    # ==================================================================
    # 配置
    # ==================================================================
    def update_config(self, room: Room, player: Player, patch: dict[str, Any]) -> GameConfig:
        """只有队长、且只在 LOBBY 能改配置。"""
        if player.id != room.captain_id:
            raise GameError("NOT_CAPTAIN", "只有队长可以修改配置")
        if room.phase is not Phase.LOBBY:
            raise GameError("WRONG_PHASE", "游戏开始后不能修改配置")
        if not isinstance(patch, dict) or not patch:
            raise GameError("INVALID_PAYLOAD", "配置必须是对象")
        raw_mode = patch.pop("gameMode", None)
        new_config, errors = room.config.patched(patch, player_count=room.count)
        if errors:
            raise GameError("INVALID_CONFIG", "；".join(errors))
        if raw_mode is not None:
            if raw_mode not in (GameMode.REAL.value, GameMode.PERSONA.value):
                raise GameError("INVALID_CONFIG", "gameMode 只能是 REAL 或 PERSONA")
            room.game_mode = raw_mode
        room.config = new_config
        return new_config

    # ==================================================================
    # 开局
    # ==================================================================
    async def start_game(self, room: Room, player: Player) -> None:
        """开始游戏：随机编号 + 逐人下发私有编号 + 进入 PHASE1。"""
        if player.id != room.captain_id:
            raise GameError("NOT_CAPTAIN", "只有队长可以开始游戏")
        if room.phase is not Phase.LOBBY:
            raise GameError("WRONG_PHASE", "游戏已经开始")
        if room.count < room.config.min_players:
            raise GameError("NOT_ENOUGH_PLAYERS", f"至少需要 {room.config.min_players} 人才能开始")
        if room.count > room.config.max_players:
            raise GameError("ROOM_FULL", f"房间人数超过上限 {room.config.max_players}")

        self.timers.cancel_room(room.code)

        # 随机分配 1..n 的编号（服务端唯一真相，永不整体下发）
        numbers = rules.assign_room_numbers([p.id for p in room.ordered_players()])
        for pid, no in numbers.items():
            room.players[pid].room_no = no

        room.started_at = time.time()
        room.round = 1
        room.winner_id = None
        room.replay = []
        room.questions.clear()

        # 每个人只收到自己的编号 + 编号数组 + 昵称数组（三者之间没有对应关系）
        nicknames = [p.nickname for p in room.ordered_players()]
        all_nos = room.room_nos()
        for p in room.ordered_players():
            await self.hub.send(
                p.id,
                {
                    "type": "game:started",
                    "roomCode": room.code,
                    "yourRoomNo": p.room_no,
                    "roomNos": all_nos,
                    "nicknames": nicknames,
                    "round": room.round,
                    "config": room.config.to_public(),
                },
            )

        # 第 2 周：LOBBY → SETUP（选模式/确认配置）→ 按模式进入不同流程
        room.phase = Phase.SETUP
        await self.broadcast_state(room)

        if room.game_mode == GameMode.PERSONA.value:
            await self.enter_card_writing(room)
        else:
            await self.enter_phase1(room)

    # ==================================================================
    # 阶段：PHASE1（提问阶段）
    # ==================================================================
    async def enter_phase1(self, room: Room) -> None:
        """进入提问阶段：每人一次行动机会，限时 phase1_seconds。"""
        self.timers.cancel_room(room.code)
        room.phase = Phase.PHASE1
        # 到点后进入「强制提交」轮：只能提交看板，答错罚 1 轮
        room.forced_submit = room.round >= room.config.forced_submit_round
        room.deadline = time.time() + room.config.phase1_seconds
        room.replay = []

        await self.broadcast(
            room,
            {
                "type": "phase:changed",
                "phase": Phase.PHASE1.value,
                "round": room.round,
                "deadline": room.deadline,
                "forcedSubmit": room.forced_submit,
                "seconds": room.config.phase1_seconds,
                "progress": self.phase1_progress(room),
            },
        )
        await self.broadcast_state(room)
        self.timers.schedule(
            TimerKey.phase1(room.code),
            room.config.phase1_seconds,
            lambda: self.on_phase1_timeout(room.code),
        )
        # AI 玩家自动行动（占位实现）
        self.schedule_ai_actions(room, room.round)

    def phase1_progress(self, room: Room) -> dict[str, Any]:
        """公开进度：谁已经行动过（不含行动内容）。"""
        acted = [p.id for p in room.ordered_players() if p.acted_in(room.round)]
        return {
            "round": room.round,
            "acted": acted,
            "total": room.count,
            "pending": [p.id for p in room.ordered_players() if not p.acted_in(room.round)],
        }

    async def on_phase1_timeout(self, room_code: str) -> None:
        """PHASE1 超时：未行动者视为放弃；强制提交轮则按「空/草稿提交」结算。"""
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE1:
            return
        log.info("PHASE1 超时 room=%s round=%s forced=%s", room_code, room.round, room.forced_submit)
        if room.forced_submit:
            for p in room.ordered_players():
                if room.phase is not Phase.PHASE1:
                    return
                if p.acted_in(room.round):
                    continue
                # 超时视为用草稿（可能是空板）提交 → 必然判错 → 罚 1 轮
                p.action_round = room.round
                p.action_kind = ActionKind.SUBMIT.value
                await self._apply_submit(room, p, rules.normalize_board(p.draft))
            if room.phase is not Phase.PHASE1:
                return
        await self.enter_phase2(room)

    # ==================================================================
    # PHASE1 三个动作
    # ==================================================================
    def _check_phase1(self, room: Room, player: Player) -> None:
        if room.phase is not Phase.PHASE1:
            raise GameError("WRONG_PHASE", "现在不是提问阶段")
        if player.acted_in(room.round):
            raise GameError("ALREADY_ACTED", "这一轮你已经行动过了")

    async def action_ask(
        self, room: Room, player: Player, target_room_no: Any, text: Any
    ) -> Question:
        """ASK：问某个编号的人一个问题（一次行动机会用掉）。"""
        self._check_phase1(room, player)
        if room.forced_submit:
            raise GameError("FORCED_SUBMIT_REQUIRED", "本轮是强制提交轮，只能提交看板")

        try:
            target_no = int(target_room_no)
        except (TypeError, ValueError):
            raise GameError("INVALID_TARGET", "目标编号必须是整数")
        target = room.player_by_room_no(target_no)
        if target is None:
            raise GameError("INVALID_TARGET", f"房间里没有编号 {target_no}")
        if target.id == player.id:
            raise GameError("INVALID_TARGET", "不能问自己")

        body = rules.sanitize_text(text, rules.ASK_TEXT_MAX)
        if not body:
            raise GameError("INVALID_PAYLOAD", "问题不能为空")

        q = Question(
            id=new_id("q"),
            asker_id=player.id,
            target_id=target.id,
            text=body,
            round=room.round,
            visibility=rules.visibility_for(room),
        )
        room.questions.append(q)
        player.action_round = room.round
        player.action_kind = ActionKind.ASK.value

        await self.broadcast_qa(room, rules.question_public_payload, q)
        if q.visibility.value == "PRIVATE":
            # 私密：只告诉其他人「本轮有一条私密问答」，不说是谁问谁
            for viewer in room.ordered_players():
                if not viewer.connected or viewer.id in (q.asker_id, q.target_id):
                    continue
                await self.hub.send(
                    viewer.id,
                    {
                        "type": "qa:privateNotice",
                        "round": room.round,
                        "text": "本轮有一条私密问答（仅当事人可见）",
                    },
                )
        # 通知被问者「有人问你了」，以及在自己队列里的位置（PHASE2 才轮到答）
        queue_pos = sum(
            1
            for x in room.round_questions()
            if x.target_id == target.id and x.status is QuestionStatus.PENDING
        )
        await self.send_to(
            room,
            target.id,
            {
                "type": "question:received",
                "round": room.round,
                "questionId": q.id,
                "askerId": player.id,
                "askerNickname": player.nickname,
                "text": body,
                "queuePosition": queue_pos,
            },
        )
        await self._after_phase1_action(room)
        return q

    async def action_submit(self, room: Room, player: Player, board_raw: Any) -> dict[str, Any]:
        """SUBMIT：提交看板，立即结算。

        校验顺序：阶段 → 冷却（比「重复行动」更具体，先拦）→ 重复行动 → 载荷。
        """
        if room.phase is not Phase.PHASE1:
            raise GameError("WRONG_PHASE", "现在不是提问阶段")
        if player.cooldown > 0 and not room.forced_submit:
            raise GameError(
                "PLAYER_IN_COOLDOWN", f"你还在冷却期，剩余 {player.cooldown} 轮，只能提问或跳过"
            )
        if player.acted_in(room.round):
            raise GameError("ALREADY_ACTED", "这一轮你已经行动过了")
        board = rules.normalize_board(board_raw)
        player.draft = {str(k): v for k, v in sorted(board.items())}
        player.action_round = room.round
        player.action_kind = ActionKind.SUBMIT.value
        player.submit_round = room.round
        player.submitted_board = dict(player.draft)

        won = await self._apply_submit(room, player, board)
        if won:
            return {"correct": True, "gameOver": True}
        await self._after_phase1_action(room)
        return {"correct": False, "gameOver": False}

    async def action_skip(self, room: Room, player: Player, board_raw: Any = None) -> None:
        """SKIP：跳过这一轮（可顺手存草稿）。"""
        self._check_phase1(room, player)
        if room.forced_submit:
            raise GameError("FORCED_SUBMIT_REQUIRED", "本轮是强制提交轮，不能跳过")
        if board_raw is not None:
            player.draft = rules.normalize_board_for_storage(board_raw)
        player.action_round = room.round
        player.action_kind = ActionKind.SKIP.value
        await self._after_phase1_action(room)

    async def _after_phase1_action(self, room: Room) -> None:
        """行动后广播进度与最新房间状态；全员行动则提前进入 PHASE2。"""
        await self.broadcast(
            room, {"type": "phase1:progress", "round": room.round, **self.phase1_progress(room)}
        )
        await self.broadcast_state(room)
        if all(p.acted_in(room.round) for p in room.active_players()):
            self.timers.cancel(TimerKey.phase1(room.code))
            await self.enter_phase2(room)

    # ==================================================================
    # 提交结算（SUBMIT 与强制提交轮共用）
    # ==================================================================
    async def _apply_submit(self, room: Room, player: Player, board: dict[int, str]) -> bool:
        """结算一次看板提交，返回是否获胜。"""
        verdict = rules.judge_board(board, room, player)
        if verdict["correct"]:
            await self.send_to(
                room,
                player.id,
                {
                    "type": "submit:result",
                    "correct": True,
                    "round": room.round,
                    "playerId": player.id,
                },
            )
            await self.game_over(room, player.id)
            return True

        was_in_cooldown = player.cooldown > 0
        new_cd = rules.cooldown_after_wrong(
            room.config, forced=room.forced_submit, was_in_cooldown=was_in_cooldown
        )
        player.cooldown = new_cd
        await self.send_to(
            room,
            player.id,
            {
                "type": "submit:result",
                "correct": False,
                "round": room.round,
                "playerId": player.id,
                "missing": verdict["missing"],
                "wrong": verdict["wrong"],
                "cooldown": new_cd,
            },
        )
        await self.broadcast(
            room,
            {
                "type": "cooldown:updated",
                "playerId": player.id,
                "cooldown": new_cd,
                "round": room.round,
                "reason": "submit_wrong",
            },
        )
        return False

    async def game_over(self, room: Room, winner_id: str) -> None:
        """结束游戏：REAL 揭晓 fullBoard，PERSONA 揭晓 reveal（卡面 + 作者）。"""
        import time as _time

        self.timers.cancel_room(room.code)
        room.phase = Phase.OVER
        room.winner_id = winner_id
        room.deadline = None
        room.finished_at = _time.time()

        payload: dict[str, Any] = {
            "type": "game:over",
            "round": room.round,
            "winnerId": winner_id,
            "gameMode": room.game_mode,
        }
        if room.game_mode == GameMode.PERSONA.value:
            payload["reveal"] = self.reveal_cards(room)
        else:
            payload["fullBoard"] = room.full_board()

        # 第 4 周：赛后复盘（名场面时间线 + 统计）
        payload["timeline"] = rules.build_timeline(room, winner_id)
        payload["stats"] = self.game_stats(room)

        await self.broadcast(room, payload)
        await self.broadcast_state(room)

        # 结束后保留一段时间可复盘，然后回收房间
        self.timers.schedule(
            TimerKey.cleanup(room.code),
            room.config.over_retention_seconds,
            lambda: self.recycle_room(room.code),
        )

    def game_stats(self, room: Room) -> dict[str, Any]:
        """谢幕页统计：轮次、问答数、超时数、高亮数。"""
        answered = sum(1 for q in room.questions if q.status is QuestionStatus.ANSWERED)
        timed_out = sum(1 for q in room.questions if q.status is QuestionStatus.TIMEOUT)
        timeline = rules.build_timeline(room, room.winner_id)
        highlights = sum(1 for item in timeline if item["highlights"])
        return {
            "rounds": room.round,
            "questions": len(room.questions),
            "answered": answered,
            "timedOut": timed_out,
            "highlights": highlights,
            "players": room.count,
            "aiPlayers": sum(1 for p in room.players.values() if p.is_ai),
        }

    def reveal_cards(self, room: Room) -> list[dict[str, Any]]:
        """PERSONA 揭晓：编号 → 卡名/卡面/作者昵称（只在 game:over 下发）。"""
        out: list[dict[str, Any]] = []
        for p in room.ordered_players():
            card = room.card_of(p)
            author = room.player(card.author_id) if card else None
            out.append(
                {
                    "roomNo": p.room_no,
                    "cardName": card.name if card else None,
                    "cardContent": card.content if card else None,
                    "authorNickname": author.nickname if author else None,
                }
            )
        return out

    def recycle_room(self, room_code: str) -> None:
        """回收房间：清定时器、摘注册表（复盘期结束）。"""
        room = self.rooms.pop(room_code, None)
        if room is None:
            return
        self.timers.cancel_room(room_code)
        for pid in list(room.players):
            self._player_room.pop(pid, None)
        log.info("回收房间 %s", room_code)

    # ==================================================================
    # 阶段：PHASE2（回答阶段，按被问者排队 + 人与人并行）
    # ==================================================================
    async def enter_phase2(self, room: Room) -> None:
        """进入回答阶段：每个被问者一条队列，队列内逐题作答，队列之间并行。"""
        room.phase = Phase.PHASE2
        room.phase2_active = {}
        pending = [q for q in room.round_questions() if q.status is QuestionStatus.PENDING]

        if not pending:
            # 本轮没人提问 → 直接进回放阶段
            room.deadline = time.time()
            await self.broadcast(
                room,
                {
                    "type": "phase:changed",
                    "phase": Phase.PHASE2.value,
                    "round": room.round,
                    "deadline": room.deadline,
                    "seconds": 0,
                    "pendingQuestions": 0,
                },
            )
            await self.enter_phase3(room)
            return

        # 最长队列决定阶段兜底时间（每题仍是独立的 phase2Seconds）
        per_target: dict[str, int] = {}
        for q in pending:
            per_target[q.target_id] = per_target.get(q.target_id, 0) + 1
        longest = max(per_target.values())
        room.deadline = time.time() + room.config.phase2_seconds * longest

        await self.broadcast(
            room,
            {
                "type": "phase:changed",
                "phase": Phase.PHASE2.value,
                "round": room.round,
                "deadline": room.deadline,
                "seconds": room.config.phase2_seconds,
                "pendingQuestions": len(pending),
            },
        )
        await self.broadcast(room, {"type": "phase2:progress", **self.phase2_progress(room)})
        await self._notify_waiting(room)

        # 每个有问题的被问者同时起跑（并行）
        for target_id in per_target:
            await self._serve_next_for_target(room, target_id)

    def phase2_progress(self, room: Room) -> dict[str, Any]:
        """回答阶段进度：每题状态（公开信息）。"""
        qs = room.round_questions()
        return {
            "round": room.round,
            "total": len(qs),
            "answered": sum(1 for q in qs if q.status is QuestionStatus.ANSWERED),
            "timedOut": sum(1 for q in qs if q.status is QuestionStatus.TIMEOUT),
            "pending": [q.id for q in qs if q.status is QuestionStatus.PENDING],
            "active": dict(room.phase2_active),
        }

    async def _serve_next_for_target(self, room: Room, target_id: str) -> None:
        """把某位被问者队列里的第一道待答题推给他，并起一个单题定时器。"""
        pending = [
            q
            for q in room.round_questions()
            if q.target_id == target_id and q.status is QuestionStatus.PENDING
        ]
        target = room.player(target_id)
        if not pending:
            room.phase2_active.pop(target_id, None)
            return

        q = pending[0]
        room.phase2_active[target_id] = q.id
        q.deadline = time.time() + room.config.phase2_seconds
        asker = room.player(q.asker_id)

        await self.send_to(
            room,
            target_id,
            {
                "type": "phase2:nextQuestion",
                "round": room.round,
                "questionId": q.id,
                "askerId": q.asker_id,
                "askerNickname": asker.nickname if asker else "?",
                "text": q.text,
                "deadline": q.deadline,
                "seconds": room.config.phase2_seconds,
                "remaining": len(pending) - 1,
            },
        )
        self.timers.schedule(
            TimerKey.question(room.code, q.id),
            room.config.phase2_seconds,
            lambda: self.on_question_timeout(room.code, q.id),
        )
        if target is not None:
            log.debug("推题 room=%s target=%s q=%s", room.code, target.nickname, q.id)
            if target.is_ai:
                # AI 自动作答（占位实现，第 3 周换成 LLM）
                self.timers.schedule(
                    TimerKey.ai_turn(room.code, q.id),
                    0.5,
                    lambda qid=q.id: self._ai_answer(room.code, qid),
                )

    async def _notify_waiting(self, room: Room) -> None:
        """告诉提问者：你的问题在队列里，等答 / 已答。"""
        for p in room.ordered_players():
            mine = [q for q in room.round_questions() if q.asker_id == p.id]
            if not mine:
                continue
            waiting = [q.id for q in mine if q.status is QuestionStatus.PENDING]
            answered = [q.id for q in mine if q.status is not QuestionStatus.PENDING]
            if not waiting and not answered:
                continue
            await self.send_to(
                room,
                p.id,
                {
                    "type": "phase2:waiting",
                    "round": room.round,
                    "waiting": waiting,
                    "answered": answered,
                },
            )

    async def action_answer(
        self, room: Room, player: Player, question_id: Any, text: Any
    ) -> dict[str, Any]:
        """ANSWER：被问者回答自己队列里的当前问题。"""
        if room.phase is not Phase.PHASE2:
            raise GameError("WRONG_PHASE", "现在不是回答阶段")
        q = self._find_round_question(room, question_id)
        if q is None:
            raise GameError("QUESTION_NOT_FOUND", "问题不存在或不属于本轮")
        if q.target_id != player.id:
            raise GameError("NOT_YOUR_QUESTION", "这道题不是问你的")
        if q.status is not QuestionStatus.PENDING:
            raise GameError("ALREADY_ANSWERED", "这道题已经结束（已答或超时）")

        body = rules.sanitize_text(text, rules.ANSWER_TEXT_MAX)
        if not body:
            raise GameError("INVALID_PAYLOAD", "回答不能为空")

        q.answer = body
        q.status = QuestionStatus.ANSWERED
        self.timers.cancel(TimerKey.question(room.code, q.id))
        await self.broadcast_qa(room, rules.answer_public_payload, q)
        await self._after_answer(room, q.target_id)
        return {"questionId": q.id, "status": q.status.value}

    def _find_round_question(self, room: Room, question_id: Any) -> Question | None:
        if not isinstance(question_id, str):
            return None
        for q in room.round_questions():
            if q.id == question_id:
                return q
        return None

    async def on_question_timeout(self, room_code: str, question_id: str) -> None:
        """单题超时：记 TIMEOUT，不惩罚，继续该被问者的队列。"""
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE2:
            return
        q = self._find_round_question(room, question_id)
        if q is None or q.status is not QuestionStatus.PENDING:
            return
        q.status = QuestionStatus.TIMEOUT
        q.answer = None
        log.info("题目超时 room=%s q=%s", room_code, question_id)
        await self.broadcast_qa(room, rules.answer_public_payload, q)
        await self._after_answer(room, q.target_id)

    async def _after_answer(self, room: Room, target_id: str) -> None:
        """一道题结束后：更新进度 → 推下一题 → 全部结束则进 PHASE3。"""
        await self.broadcast(room, {"type": "phase2:progress", **self.phase2_progress(room)})
        if room.phase is not Phase.PHASE2:
            return
        await self._serve_next_for_target(room, target_id)
        await self._notify_waiting(room)
        still_pending = any(
            q.status is QuestionStatus.PENDING for q in room.round_questions()
        )
        if not still_pending:
            self.timers.cancel(TimerKey.phase2(room.code))
            await self.enter_phase3(room)

    # ==================================================================
    # 阶段：PHASE3（回放确认）
    # ==================================================================
    async def enter_phase3(self, room: Room) -> None:
        """进入回放阶段：把本轮公开问答整段回放，全员确认或超时后结束本轮。"""
        room.phase = Phase.PHASE3
        room.phase2_active = {}
        room.deadline = time.time() + room.config.phase3_seconds
        items = rules.build_replay_items(room)
        room.replay = items

        auto_confirmed: list[str] = [
            p.id for p in room.ordered_players() if p.confirmed_round == room.round
        ]

        await self.broadcast(
            room, {"type": "phase3:replay", "round": room.round, "items": items}
        )
        await self.broadcast(
            room,
            {
                "type": "phase:changed",
                "phase": Phase.PHASE3.value,
                "round": room.round,
                "deadline": room.deadline,
                "seconds": room.config.phase3_seconds,
                "confirmed": auto_confirmed,
                "total": len(room.active_players()),
            },
        )
        await self.broadcast_state(room)
        self.timers.schedule(
            TimerKey.phase3(room.code),
            room.config.phase3_seconds,
            lambda: self.on_phase3_timeout(room.code),
        )
        # AI 延迟 1–3s 自动确认回放
        self.schedule_ai_confirm(room)

    async def on_phase3_timeout(self, room_code: str) -> None:
        """回放超时 → 结束本轮。"""
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE3:
            return
        log.info("PHASE3 超时 room=%s round=%s", room_code, room.round)
        await self.end_round(room)

    async def action_confirm(self, room: Room, player: Player) -> dict[str, Any]:
        """CONFIRM：回放阶段确认（全员确认或超时都结束本轮）。"""
        if room.phase is not Phase.PHASE3:
            raise GameError("WRONG_PHASE", "现在不是回放阶段")
        if player.confirmed_round == room.round:
            raise GameError("ALREADY_CONFIRMED", "这一轮你已经确认过了")
        player.confirmed_round = room.round
        confirmed = [p.id for p in room.ordered_players() if p.confirmed_round == room.round]
        await self.broadcast(
            room,
            {
                "type": "phase3:progress",
                "round": room.round,
                "confirmed": confirmed,
                "total": len(room.active_players()),
            },
        )
        if len(confirmed) == len(room.active_players()):
            self.timers.cancel(TimerKey.phase3(room.code))
            await self.end_round(room)
        return {"confirmed": len(confirmed), "total": room.count}

    # ==================================================================
    # 一轮结束
    # ==================================================================
    async def end_round(self, room: Room) -> None:
        """结束本轮：所有冷却 -1 并广播，然后进入下一轮 PHASE1。"""
        if room.phase is Phase.OVER:
            return
        self.timers.cancel_room(room.code)

        # 每轮结束所有冷却 -1（服务端权威）
        changed = rules.decrement_cooldowns(room)
        for item in changed:
            await self.broadcast(
                room,
                {
                    "type": "cooldown:updated",
                    "playerId": item["playerId"],
                    "cooldown": item["cooldown"],
                    "round": room.round,
                    "reason": "round_end",
                },
            )

        room.round += 1
        room.replay = []
        room.phase2_active = {}
        log.info("本轮结束 room=%s → round=%s", room.code, room.round)
        await self.broadcast(
            room,
            {
                "type": "round:ended",
                "endedRound": room.round - 1,
                "nextRound": room.round,
            },
        )
        await self.enter_phase1(room)

    # ==================================================================
    # 第 2 周：人设卡流程（CARD_WRITING → READING → ROUND_START）
    # ==================================================================
    async def enter_card_writing(self, room: Room) -> None:
        """写卡阶段：每人交一张卡，不设硬超时。"""
        room.phase = Phase.CARD_WRITING
        room.deadline = None
        room.cards = []
        room.card_submitted = set()
        room.assigned = False
        for p in room.ordered_players():
            p.card_submitted = False
            p.assigned_card_id = None
            p.reading_confirmed = False

        await self.broadcast(
            room,
            {
                "type": "phase:changed",
                "phase": Phase.CARD_WRITING.value,
                "status": "CARD_WRITING",
                "round": room.round,
                "deadline": None,
                "gameMode": room.game_mode,
            },
        )
        await self.broadcast(
            room, {"type": "card:progress", "submitted": 0, "total": room.count}
        )
        await self.broadcast_state(room)

        # AI 玩家自动写卡（LLM 生成 + 短暂延迟，制造压迫感）
        for p in room.ordered_players():
            if p.is_ai:
                asyncio.create_task(self._ai_write_card(room, p))

    async def submit_card(self, room: Room, player: Player, name: Any, content: Any) -> PersonaCard:
        """提交人设卡：卡名 1–20 字且同房间唯一，卡面 ≤300 字。"""
        if room.phase is not Phase.CARD_WRITING:
            raise GameError("WRONG_PHASE", "现在不是写卡阶段")
        if player.card_submitted:
            raise GameError("ALREADY_SUBMITTED", "你已经交过卡了")

        card_name = rules.normalize_card_name(name, room.card_names())
        card_content = rules.normalize_card_content(content)

        card = PersonaCard(
            id=new_id("c"),
            game_id=room.code,
            author_id=player.id,
            name=card_name,
            content=card_content,
        )
        room.cards.append(card)
        room.card_submitted.add(player.id)
        player.card_submitted = True

        await self.send_to(
            room,
            player.id,
            {"type": "card:submitted", "ok": True, "card": {"name": card.name, "content": card.content}},
        )
        await self.broadcast(
            room,
            {
                "type": "card:progress",
                "submitted": len(room.card_submitted),
                "total": room.count,
            },
        )
        await self.broadcast_state(room)
        return card

    async def start_assign(self, room: Room, player: Player) -> None:
        """队长触发错位分配（仅 PERSONA、仅全员交齐）。"""
        if room.phase is not Phase.CARD_WRITING:
            raise GameError("WRONG_PHASE", "现在不是写卡阶段")
        if player.id != room.captain_id:
            raise GameError("NOT_CAPTAIN", "只有队长可以开始分配")
        if len(room.card_submitted) < room.count:
            raise GameError(
                "CARDS_NOT_READY",
                f"还有 {room.count - len(room.card_submitted)} 人没交卡",
            )

        mapping = rules.derange(list(room.cards), room.ordered_players())
        for pid, card in mapping.items():
            owner = room.players[pid]
            owner.assigned_card_id = card.id
            card.assigned_room_no = owner.room_no
        room.assigned = True

        for p in room.ordered_players():
            p.board_json = {}
            p.submit_cooldown = 0
            p.reading_confirmed = False

        log.info("人设卡分配完成 room=%s players=%s", room.code, room.count)
        await self.enter_reading(room)

    def persona_assigned_payload(self, room: Room, player: Player) -> dict[str, Any]:
        """persona:assigned：只给本人卡面 + 打乱顺序的卡名表，不含任何映射。"""
        import random as _random
        import time as _time

        card = room.card_of(player)
        names = room.card_names()
        _random.shuffle(names)
        return {
            "type": "persona:assigned",
            "yourRoomNo": player.room_no,
            "roomNos": room.room_nos(),
            "yourCard": {"name": card.name, "content": card.content} if card else None,
            "cardNames": names,
            "deadline": room.deadline,
        }

    async def enter_reading(self, room: Room) -> None:
        """阅读阶段：3 分钟（可配）读自己的人设卡，全员示意或超时进入轮次。"""
        import time as _time

        room.phase = Phase.READING
        room.deadline = _time.time() + room.config.reading_seconds
        for p in room.ordered_players():
            # AI 玩家没有「阅读」这个动作，直接视为已示意，避免卡住全员门槛
            p.reading_confirmed = bool(p.is_ai)

        for p in room.ordered_players():
            if not p.connected:
                continue
            await self.send_to(room, p.id, self.persona_assigned_payload(room, p))

        await self.broadcast(
            room,
            {
                "type": "phase:changed",
                "phase": Phase.READING.value,
                "status": "READING",
                "round": room.round,
                "deadline": room.deadline,
                "seconds": room.config.reading_seconds,
                "gameMode": room.game_mode,
            },
        )
        await self.broadcast(
            room,
            {
                "type": "reading:progress",
                "confirmed": sum(1 for p in room.ordered_players() if p.reading_confirmed),
                "total": len(room.active_players()),
            },
        )
        await self.broadcast_state(room)
        self.timers.schedule(
            TimerKey.reading(room.code),
            room.config.reading_seconds,
            lambda: self.on_reading_timeout(room.code),
        )

    async def confirm_reading(self, room: Room, player: Player) -> dict[str, Any]:
        """阅读阶段示意：全员示意或超时即进入第一幕。"""
        if room.phase is not Phase.READING:
            raise GameError("WRONG_PHASE", "现在不是阅读阶段")
        if player.reading_confirmed:
            raise GameError("ALREADY_CONFIRMED", "你已示意过了")
        player.reading_confirmed = True

        active = room.active_players()
        confirmed = [p.id for p in active if p.reading_confirmed]
        await self.broadcast(
            room,
            {
                "type": "reading:progress",
                "confirmed": len(confirmed),
                "total": len(active),
            },
        )
        if len(confirmed) == len(active):
            self.timers.cancel(TimerKey.reading(room.code))
            await self.enter_phase1(room)
        return {"confirmed": len(confirmed), "total": len(active)}

    async def on_reading_timeout(self, room_code: str) -> None:
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.READING:
            return
        log.info("阅读阶段超时 room=%s", room_code)
        await self.enter_phase1(room)

    # ==================================================================
    # 第 2 周：重连 / 心跳 / 房间回收
    # ==================================================================
    def register_session(self, player_id: str, session: Any) -> None:
        self.sessions[player_id] = session

    def unregister_session(self, player_id: str, session: Any) -> None:
        if self.sessions.get(player_id) is session:
            self.sessions.pop(player_id, None)

    def touch_session(self, player_id: str) -> None:
        import time as _time

        session = self.sessions.get(player_id)
        if session is not None:
            session.last_seen = _time.time()

    def snapshot_for(self, room: Room, player: Player) -> dict[str, Any]:
        """重连快照：当前阶段 + 本人该看到的一切（绝不含映射）。"""
        card = room.card_of(player)
        payload: dict[str, Any] = {
            "roomCode": room.code,
            "status": room.status,
            "phase": room.phase.value,
            "gameMode": room.game_mode,
            "round": room.round,
            "deadline": room.deadline,
            "captainId": room.captain_id,
            "players": [p.public_view() for p in room.ordered_players()],
            "config": room.config.to_public(),
            "yourRoomNo": player.room_no,
            "roomNos": room.room_nos(),
            "nicknames": [p.nickname for p in room.ordered_players()],
            "board": dict(player.draft),
            "cooldown": player.cooldown,
            "acted": player.acted_in(room.round),
            "cardSubmitted": player.card_submitted,
            "readingConfirmed": player.reading_confirmed,
            "replay": list(room.replay),
        }
        if room.game_mode == GameMode.PERSONA.value:
            payload["cards"] = {
                "submitted": len(room.card_submitted),
                "assigned": room.assigned,
            }
            if card is not None:
                names = room.card_names()
                payload["yourCard"] = {"name": card.name, "content": card.content}
                payload["cardNames"] = names
        if room.phase is Phase.PHASE2:
            active = room.phase2_active.get(player.id)
            question = self._find_round_question(room, active) if active else None
            if question is not None and question.status is QuestionStatus.PENDING:
                payload["currentQuestion"] = {
                    "questionId": question.id,
                    "askerId": question.asker_id,
                    "text": question.text,
                    "deadline": question.deadline,
                }
        return payload

    def reconnect(self, room_code: Any, player_id: Any, token: Any) -> tuple[Room, Player]:
        """校验重连凭据，恢复座位。"""
        code = room_code.strip() if isinstance(room_code, str) else ""
        room = self.rooms.get(code)
        player = room.player(player_id) if room and isinstance(player_id, str) else None
        if room is None or player is None:
            raise GameError("RECONNECT_INVALID", "房间或座位不存在")
        if not isinstance(token, str) or not player.reconnect_token or token != player.reconnect_token:
            raise GameError("RECONNECT_INVALID", "重连凭据无效")
        player.connected = True
        self._player_room[player.id] = room.code
        return room, player

    async def start_watchdog(self) -> None:
        """心跳看门狗：每 2 秒扫一遍，超过该房间 heartbeat_seconds 没动静就标掉线。"""
        import asyncio as _asyncio
        import time as _time

        if getattr(self, "_watchdog", None) is not None:
            return

        async def loop() -> None:
            while True:
                await _asyncio.sleep(2)
                now = _time.time()
                for room in list(self.rooms.values()):
                    if room.phase is Phase.OVER:
                        continue
                    changed = False
                    timeout = room.config.heartbeat_seconds
                    for p in room.ordered_players():
                        if not p.connected:
                            continue
                        session = self.sessions.get(p.id)
                        if session is None:
                            continue
                        last = getattr(session, "last_seen", None)
                        if last is None:
                            continue
                        if now - last > timeout:
                            p.connected = False
                            changed = True
                            log.info("心跳超时判定掉线 room=%s player=%s", room.code, p.id)
                    if changed:
                        await self.broadcast_state(room)

        self._watchdog = _asyncio.create_task(loop(), name="heartbeat-watchdog")

    async def stop_watchdog(self) -> None:
        import asyncio as _asyncio

        task = getattr(self, "_watchdog", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (_asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._watchdog = None

    # ==================================================================
    # 第 3 周：AI 玩家（LLM 驱动，与真人共用同一套 action_* 校验）
    # ==================================================================
    def add_ai_player(self, room: Room, captain: Player, nickname: Any = None) -> Player:
        """兼容第 2 周的 captain:addAi：加一个指定昵称的 AI。"""
        if captain.id != room.captain_id:
            raise GameError("NOT_CAPTAIN", "只有队长可以添加 AI")
        if room.phase is not Phase.LOBBY:
            raise GameError("WRONG_PHASE", "只能在等待室添加 AI")
        if room.count >= room.config.max_players:
            raise GameError("ROOM_FULL", "房间已满")
        nick = rules.normalize_nickname(nickname or self._next_ai_nickname(room))
        if room.by_nickname(nick) is not None:
            raise GameError("NICKNAME_TAKEN", "这个昵称已被占用")
        bot = Player(
            id=new_id("p"),
            nickname=nick,
            reconnect_token=new_id("rt"),
            is_ai=True,
            connected=True,
        )
        room.players[bot.id] = bot
        self._player_room[bot.id] = room.code
        log.info("添加 AI room=%s nick=%s", room.code, nick)
        return bot

    def add_ai_players(self, room: Room, captain: Player, count: Any = 1) -> list[Player]:
        """队长在等待室放 AI 进来（一次 1–2 个）。"""
        if captain.id != room.captain_id:
            raise GameError("NOT_CAPTAIN", "只有队长可以添加 AI")
        if room.phase is not Phase.LOBBY:
            raise GameError("WRONG_PHASE", "只能在等待室添加 AI")
        try:
            wanted = int(count)
        except (TypeError, ValueError):
            raise GameError("INVALID_PAYLOAD", "count 必须是整数") from None
        if not 1 <= wanted <= 2:
            raise GameError("INVALID_PAYLOAD", "一次只能加 1–2 个 AI")
        if room.count + wanted > room.config.max_players:
            raise GameError("ROOM_FULL", "房间位置不够了")

        added: list[Player] = []
        for _ in range(wanted):
            added.append(self.add_ai_player(room, captain, self._next_ai_nickname(room)))
        return added

    def _next_ai_nickname(self, room: Room) -> str:
        taken = {p.nickname for p in room.players.values()}
        for name in ai.AI_NICKNAMES:
            if name not in taken:
                return name
        index = 1
        while f"木偶·{index}" in taken:
            index += 1
        return f"木偶·{index}"

    def ai_debug_log(self, room: Room, player: Player, kind: str, payload: Any) -> None:
        """留痕：/debug/ai 与防泄题测试都读这里。"""
        self.ai_log.append(
            {
                "room": room.code,
                "playerId": player.id,
                "nickname": player.nickname,
                "kind": kind,
                "payload": payload,
            }
        )
        self.ai_log[:] = self.ai_log[-200:]

    async def _ai_thinking(self, room: Room, player: Player, kind: str) -> None:
        """广播「AI 正在想」，给真人做进度反馈（不含私有信息）。"""
        await self.broadcast(
            room,
            {
                "type": "ai:thinking",
                "playerId": player.id,
                "nickname": player.nickname,
                "kind": kind,
            },
        )

    # ---------------- 写卡 ----------------
    async def _ai_write_card(self, room: Room, bot: Player) -> None:
        """AI 写卡：LLM 生成 → 延迟 → 提交（重名自动换名重试）。"""
        if room.phase is not Phase.CARD_WRITING or bot.card_submitted:
            return
        await self._ai_thinking(room, bot, "write_card")
        try:
            data = await ai_agent.write_card(
                room, bot, timeout=room.config.ai_llm_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("AI 写卡异常，用兜底卡: %s", exc)
            data = ai.generate_ai_card()
        self.ai_debug_log(room, bot, "write_card", data)

        async def _submit() -> None:
            current = self.rooms.get(room.code)
            if current is None or current.phase is not Phase.CARD_WRITING:
                return
            if bot.card_submitted:
                return
            try:
                await self.submit_card(current, bot, data["name"], data["content"])
            except GameError as exc:
                log.info("AI 交卡被拒（%s），换名重试", exc.code)
                retry = ai.generate_ai_card()
                name = retry["name"]
                suffix = 1
                while name in current.card_names():
                    suffix += 1
                    name = f"{retry['name'][:16]}·{suffix}"
                try:
                    await self.submit_card(current, bot, name, retry["content"])
                except GameError:
                    pass

        self.timers.schedule(
            TimerKey.ai_turn(room.code, f"card:{bot.id}"),
            room.config.ai_card_delay_seconds,
            _submit,
        )

    # ---------------- 第一幕 ----------------
    def schedule_ai_actions(self, room: Room, round_no: int) -> None:
        """第一幕：每个 AI 排一个 5–10s 级别的随机延迟后再决策。"""
        for p in room.ordered_players():
            if not p.is_ai:
                continue
            base = max(0.0, room.config.ai_think_seconds)
            delay = base * random.uniform(0.8, 1.7) if base > 0 else 0.0
            self.timers.schedule(
                TimerKey.ai_turn(room.code, f"p1:{p.id}:{round_no}"),
                delay,
                lambda pid=p.id: self._ai_phase1_action(room.code, pid),
            )

    async def _ai_phase1_action(self, room_code: str, player_id: str) -> None:
        """AI 第一幕：ASK / SUBMIT / SKIP，全部走真人同款校验。"""
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE1:
            return
        bot = room.player(player_id)
        if bot is None or not bot.is_ai or bot.acted_in(room.round):
            return

        await self._ai_thinking(room, bot, "phase1")
        try:
            decision = await ai_agent.decide_phase1(
                room, bot, timeout=room.config.ai_llm_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("AI 第一幕决策异常，放弃本轮: %s", exc)
            decision = {"action": "SKIP"}
        self.ai_debug_log(room, bot, "phase1", decision)

        try:
            if decision.get("action") == "ASK":
                await self.action_ask(
                    room, bot, decision.get("targetRoomNo"), decision.get("text")
                )
            elif decision.get("action") == "SUBMIT":
                # 提交前的「推理轮」：模型先推一遍，不成再用约束传播
                verdict = await ai_agent.decide_submit(
                    room, bot, timeout=room.config.ai_llm_timeout_seconds
                )
                self.ai_debug_log(room, bot, "submit", verdict)
                await self.action_submit(room, bot, verdict.get("board"))
            else:
                await self.action_skip(room, bot)
        except GameError as exc:
            log.info("AI 第一幕动作被拒（%s），改为放弃", exc.code)
            try:
                await self.action_skip(room, bot)
            except GameError:
                pass

    # ---------------- 第二幕 ----------------
    async def _ai_answer(self, room_code: str, question_id: str) -> None:
        """AI 被问：按人设作答（打字延迟后提交）。"""
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE2:
            return
        question = self._find_round_question(room, question_id)
        if question is None or question.status is not QuestionStatus.PENDING:
            return
        target = room.player(question.target_id)
        if target is None or not target.is_ai:
            return

        await self._ai_thinking(room, target, "answer")
        try:
            text = await ai_agent.answer_question(
                room, target, question, timeout=room.config.ai_llm_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("AI 作答异常，用兜底台词: %s", exc)
            text = ai.ai_answer_as_persona(room.card_of(target), question.text)
        self.ai_debug_log(room, target, "answer", {"question": question.text, "answer": text})

        base = max(0.0, room.config.ai_answer_delay_seconds)
        delay = min(5.0, base * max(0.5, len(text) / 40.0)) if base > 0 else 0.0

        async def _submit() -> None:
            current = self.rooms.get(room.code)
            if current is None or current.phase is not Phase.PHASE2:
                return
            q = self._find_round_question(current, question_id)
            if q is None or q.status is not QuestionStatus.PENDING:
                return
            try:
                await self.action_answer(current, target, question_id, text)
            except GameError:
                pass

        self.timers.schedule(
            TimerKey.ai_turn(room.code, f"ans:{question_id}"), delay, _submit
        )

    # ---------------- 第三幕 ----------------
    def schedule_ai_confirm(self, room: Room) -> None:
        """回放阶段：AI 延迟 1–3s 自动确认。"""
        base = max(0.0, room.config.ai_confirm_delay_seconds)
        for p in room.ordered_players():
            if not p.is_ai:
                continue
            delay = base * random.uniform(0.6, 1.5) if base > 0 else 0.0
            self.timers.schedule(
                TimerKey.ai_turn(room.code, f"p3:{p.id}:{room.round}"),
                delay,
                lambda pid=p.id: self._ai_confirm(room.code, pid),
            )

    async def _ai_confirm(self, room_code: str, player_id: str) -> None:
        room = self.rooms.get(room_code)
        if room is None or room.phase is not Phase.PHASE3:
            return
        bot = room.player(player_id)
        if bot is None or not bot.is_ai or bot.confirmed_round == room.round:
            return
        try:
            await self.action_confirm(room, bot)
        except GameError:
            pass
