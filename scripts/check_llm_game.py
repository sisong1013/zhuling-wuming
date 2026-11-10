"""用游戏真实 Prompt 走一遍：AI 写卡 + AI 按人设作答。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.main  # noqa: E402,F401
from server import ai, ai_agent, llm_client  # noqa: E402
from server.models import GameConfig, GameMode, PersonaCard, Player, Room  # noqa: E402


def make_room():
    room = Room(code="000111", config=GameConfig())
    room.game_mode = GameMode.PERSONA.value
    players = [Player(id=f"p{i}", nickname=n, room_no=i + 1) for i, n in enumerate(["甲", "乙", "丙"])]
    room.players = {p.id: p for p in players}
    room.captain_id = players[0].id
    cards = []
    for i, p in enumerate(players):
        card = PersonaCard(
            id=f"c{i}", game_id=room.code, author_id=p.id, name=f"占位卡{i + 1}", content="占位"
        )
        card.assigned_room_no = p.room_no
        p.assigned_card_id = card.id
        cards.append(card)
    room.cards = cards
    room.assigned = True
    return room, players


async def main() -> None:
    print("llm:", llm_client.stats()["configured"], llm_client.model_chain(), "budget", llm_client.max_tokens())

    for _ in range(2):
        card = await ai.generate_ai_card_async(timeout=60)
        print("卡:", card["name"], "|", card["content"][:70])

    room, players = make_room()
    bot = players[2]
    text = await ai.ai_answer_as_persona_async(
        room.card_of(bot), "你昨晚在那盏灯下待了多久？", timeout=60
    )
    print("答:", text)

    verdict = await ai_agent.decide_submit(room, bot, timeout=60)
    print("推理轮:", verdict["source"], "|", verdict.get("reasoning"), "|", verdict["board"])

    print("stats:", llm_client.stats())


if __name__ == "__main__":
    asyncio.run(main())
