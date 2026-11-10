"""第 2 周：state_machine.py 大改（多房间别名/重连/人设卡三阶段/AI stub 接入）。"""

from __future__ import annotations

from pathlib import Path

P = Path(__file__).resolve().parents[1] / "server" / "state_machine.py"
s = P.read_text(encoding="utf-8")
missing: list[str] = []


def swap(old: str, new: str, label: str) -> None:
    global s
    if old in s:
        s = s.replace(old, new, 1)
    else:
        missing.append(label)


# ---------------------------------------------------------------- 导入
swap(
    "from . import rules\n",
    "from . import ai as ai_stub\nfrom . import rules\n",
    "import ai",
)
swap(
    """from .models import (
    ActionKind,
    GameConfig,
    GameError,
    Phase,
    Player,
    Question,
    QuestionStatus,
    Room,
    new_id,
)""",
    """from .models import (
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
)""",
    "imports models",
)

# ---------------------------------------------------------------- games 别名
swap(
    "        self.rooms: dict[str, Room] = {}\n",
    "        self.rooms: dict[str, Room] = {}\n        self.sessions: dict[str, Any] = {}  # player_id → Session（心跳用）\n",
    "sessions dict",
)

# ---------------------------------------------------------------- 建房/加入：签重连令牌
swap(
    """        player = Player(id=new_id("p"), nickname=nick, is_captain=True)""",
    """        player = Player(
            id=new_id("p"),
            nickname=nick,
            is_captain=True,
            reconnect_token=new_id("rt"),
        )""",
    "create token",
)
swap(
    """        player = Player(id=new_id("p"), nickname=nick)
        room.players[player.id] = player
        self._player_room[player.id] = code""",
    """        player = Player(id=new_id("p"), nickname=nick, reconnect_token=new_id("rt"))
        room.players[player.id] = player
        self._player_room[player.id] = code""",
    "join token",
)

# ---------------------------------------------------------------- start_game：先 SETUP 再按模式分支
swap(
    """        await self.broadcast_state(room)
        await self.enter_phase1(room)

    # ==================================================================
    # 阶段：PHASE1（提问阶段）""",
    """        # 第 2 周：LOBBY → SETUP（选模式/确认配置）→ 按模式进入不同流程
        room.phase = Phase.SETUP
        await self.broadcast_state(room)

        if room.game_mode == GameMode.PERSONA.value:
            await self.enter_card_writing(room)
        else:
            await self.enter_phase1(room)

    # ==================================================================
    # 阶段：PHASE1（提问阶段）""",
    "start_game branch",
)

# ---------------------------------------------------------------- 全员行动只看在线
swap(
    """        if all(p.acted_in(room.round) for p in room.ordered_players()):""",
    """        if all(p.acted_in(room.round) for p in room.active_players()):""",
    "phase1 all acted",
)
swap(
    """        if len(confirmed) == room.count:""",
    """        if len(confirmed) == len(room.active_players()):""",
    "phase3 all confirmed",
)
swap(
    """                "total": room.count,
            },
        )
        if len(confirmed) == len(room.active_players()):""",
    """                "total": len(room.active_players()),
            },
        )
        if len(confirmed) == len(room.active_players()):""",
    "phase3 total",
)

# ---------------------------------------------------------------- game_over：模式化揭晓 + 回收计时
swap(
    """    async def game_over(self, room: Room, winner_id: str) -> None:
        \"\"\"结束游戏：此时才揭晓完整映射。\"\"\"
        self.timers.cancel_room(room.code)
        room.phase = Phase.OVER
        room.winner_id = winner_id
        room.deadline = None
        await self.broadcast(
            room,
            {
                "type": "game:over",
                "round": room.round,
                "winnerId": winner_id,
                "fullBoard": room.full_board(),
            },
        )
        await self.broadcast_state(room)""",
    """    async def game_over(self, room: Room, winner_id: str) -> None:
        \"\"\"结束游戏：REAL 揭晓 fullBoard，PERSONA 揭晓 reveal（卡面 + 作者）。\"\"\"
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

        await self.broadcast(room, payload)
        await self.broadcast_state(room)

        # 结束后保留一段时间可复盘，然后回收房间
        self.timers.schedule(
            TimerKey.cleanup(room.code),
            room.config.over_retention_seconds,
            lambda: self.recycle_room(room.code),
        )

    def reveal_cards(self, room: Room) -> list[dict[str, Any]]:
        \"\"\"PERSONA 揭晓：编号 → 卡名/卡面/作者昵称（只在 game:over 下发）。\"\"\"
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
        \"\"\"回收房间：清定时器、摘注册表（复盘期结束）。\"\"\"
        room = self.rooms.pop(room_code, None)
        if room is None:
            return
        self.timers.cancel_room(room_code)
        for pid in list(room.players):
            self._player_room.pop(pid, None)
        log.info("回收房间 %s", room_code)""",
    "game_over",
)

# ---------------------------------------------------------------- 配置：支持 gameMode
swap(
    """        new_config, errors = room.config.patched(patch, player_count=room.count)
        if errors:
            raise GameError("INVALID_CONFIG", "；".join(errors))
        room.config = new_config
        return new_config""",
    """        raw_mode = patch.pop("gameMode", None)
        new_config, errors = room.config.patched(patch, player_count=room.count)
        if errors:
            raise GameError("INVALID_CONFIG", "；".join(errors))
        if raw_mode is not None:
            if raw_mode not in (GameMode.REAL.value, GameMode.PERSONA.value):
                raise GameError("INVALID_CONFIG", "gameMode 只能是 REAL 或 PERSONA")
            room.game_mode = raw_mode
        room.config = new_config
        return new_config""",
    "update_config gameMode",
)

P.write_text(s, encoding="utf-8")
print("missing:", missing)
print("bytes:", len(s))
