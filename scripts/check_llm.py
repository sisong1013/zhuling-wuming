"""对真实网关做一次端到端校验：普通调用 + 强制 JSON 调用。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.main  # noqa: E402,F401  (导入即加载 config/llm.json)
from server import llm_client  # noqa: E402


async def main() -> None:
    print("configured:", llm_client.is_available())
    print("base:", llm_client.base_url())
    print("chain:", llm_client.model_chain())

    text = await llm_client.call_llm(
        "你是一个简洁的助手。", "只回四个字：台上见。不要标点。", timeout=40
    )
    print("plain ->", repr(text[:120]))

    data = await llm_client.call_llm_json(
        "你只输出 JSON 对象。",
        '请输出 {"ok": true, "who": "诸伶无名"}',
        timeout=40,
    )
    print("json  ->", data)

    card = await llm_client.call_llm_json(
        "你在为社交推理游戏写人设卡。只输出 JSON：{\"name\":\"卡名\",\"content\":\"40-120字的卡面\"}",
        "生成一张新的人设卡，卡名 4-14 个汉字。",
        timeout=40,
    )
    print("card  ->", card)
    print("stats ->", llm_client.stats())


if __name__ == "__main__":
    asyncio.run(main())
