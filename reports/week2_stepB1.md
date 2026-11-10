# 第 2 周 · Step B1：游戏模式 REAL / PERSONA

- 状态：**完成**（本步用例 6 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/models.py`：`GameMode` 枚举、`Room.game_mode`（默认 REAL）
- `server/state_machine.py`：`update_config` 支持 `gameMode`（只接受 REAL/PERSONA），开局后改模式回 `WRONG_PHASE`；`start_game` 按模式分叉到 `enter_card_writing` 或 `enter_phase1`
- `tests/test_week2_stepB1_mode.py`：6 条用例

## 测试

本步新增 **6** 条用例，覆盖本步全部规则断言。

## 已知限制

- REAL 流程与第 1 周完全一致（第 1 周 64 条测试全绿，作为回归证明）

## 下一步：B2 写卡阶段

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
