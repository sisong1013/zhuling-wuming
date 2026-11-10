"""服务端权威计时器：带 key、可取消。

所有阶段倒计时、单题回答倒计时都走这里。
- key 全局唯一（如 `room:123456:phase1` / `room:123456:q:q_abc`），
- 重新 schedule 同一个 key 会自动取消旧任务，
- 房间结束时按前缀批量取消，避免泄漏任务。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("game.timers")


class TimerManager:
    """一张 key → asyncio.Task 的表。"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    # ---------------- 调度 ----------------
    def schedule(self, key: str, delay: float, callback: Callable[[], Awaitable[None]]) -> None:
        """delay 秒后执行 callback；同 key 的旧定时器先取消。"""
        self.cancel(key)

        async def runner() -> None:
            try:
                await asyncio.sleep(max(0.0, float(delay)))
                await callback()
            except asyncio.CancelledError:
                raise
            except Exception:  # 定时器回调里的异常不能吞掉进程
                log.exception("定时器回调异常 key=%s", key)
            finally:
                # 只有自己还是当前任务时才摘掉，避免误删同 key 的新定时器
                if self._tasks.get(key) is asyncio.current_task():
                    self._tasks.pop(key, None)

        self._tasks[key] = asyncio.create_task(runner(), name=f"timer:{key}")

    # ---------------- 取消 ----------------
    def cancel(self, key: str) -> bool:
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def cancel_prefix(self, prefix: str) -> int:
        """按前缀批量取消（房间结束 / 阶段切换时用）。"""
        killed = 0
        for key in [k for k in self._tasks if k.startswith(prefix)]:
            if self.cancel(key):
                killed += 1
        return killed

    def cancel_room(self, room_code: str) -> int:
        return self.cancel_prefix(f"room:{room_code}:")

    # ---------------- 观测 ----------------
    def is_pending(self, key: str) -> bool:
        task = self._tasks.get(key)
        return bool(task and not task.done())

    def pending_keys(self) -> list[str]:
        return sorted(k for k, t in self._tasks.items() if not t.done())

    async def shutdown(self) -> None:
        """进程退出时清干净。"""
        for key in list(self._tasks):
            self.cancel(key)
        await asyncio.sleep(0)


class TimerKey:
    """key 命名小工具，避免各处手拼字符串出错。"""

    @staticmethod
    def phase1(room_code: str) -> str:
        return f"room:{room_code}:phase1"

    @staticmethod
    def phase2(room_code: str) -> str:
        return f"room:{room_code}:phase2"

    @staticmethod
    def phase3(room_code: str) -> str:
        return f"room:{room_code}:phase3"

    @staticmethod
    def question(room_code: str, question_id: str) -> str:
        return f"room:{room_code}:q:{question_id}"

    @staticmethod
    def reading(room_code: str) -> str:
        return f"room:{room_code}:reading"

    @staticmethod
    def ai_turn(room_code: str, question_id: str) -> str:
        return f"room:{room_code}:ai:{question_id}"

    @staticmethod
    def cleanup(room_code: str) -> str:
        return f"room:{room_code}:cleanup"

    @staticmethod
    def room_prefix(room_code: str) -> str:
        return f"room:{room_code}:"
