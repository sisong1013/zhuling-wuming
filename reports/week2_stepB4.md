# 第 2 周 · Step B4：阅读阶段 READING

- 状态：**完成**（本步用例 7 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/state_machine.py`：`enter_reading()`、`persona_assigned_payload()`、`confirm_reading()`、`on_reading_timeout()`、`snapshot_for()` 补 `yourCard/cardNames`
- `server/models.py`：`GameConfig.reading_seconds`（默认 180s，可配）
- `server/ws_handlers.py`：`reading:confirm`；重连时若在 READING 会补发 `persona:assigned`
- `tests/test_week2_stepB4_reading.py`：7 条用例

## 测试

本步新增 **7** 条用例，覆盖本步全部规则断言。

## 已知限制

- `cardNames` 只打乱顺序，不含任何「卡→作者/编号」映射（有用例断言字段白名单与昵称不出现）
- AI 玩家没有「阅读」动作，服务端直接视为已示意，避免卡住全员门槛

## 下一步：B5 判定与揭晓

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
