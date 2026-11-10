# 第 2 周 · Step A1：多房间并存与房间生命周期

- 状态：**完成**（本步用例 6 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/models.py`：`Phase` 增加 `SETUP / CARD_WRITING / READING`；`Room` 增加 `game_mode / visibility / cards / card_submitted / assigned / finished_at`；新增 `status_of()` 与 `Room.status`
- `server/state_machine.py`：`start_game` 先进入 `SETUP` 再按模式分叉；`game_over` 记录 `finished_at` 并排 `over_retention_seconds` 后的回收定时器；新增 `recycle_room()`
- `server/timers.py`：新增 `TimerKey.reading / cleanup / ai_turn`
- `tests/test_week2_stepA1_rooms.py`：6 条用例

## 测试

本步新增 **6** 条用例，覆盖本步全部规则断言。

## 已知限制

- 房间表仍是单进程内存字典 `GameRegistry.rooms`（多进程部署需外部共享层，第 3 周再考虑）
- 回收是在 `game:over` 时排定时器；服务重启会丢失所有房间（纯内存设计的前提）

## 下一步：A2 断线重连

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
