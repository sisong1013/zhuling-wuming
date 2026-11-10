# 第 2 周 · Step B3：人设卡错位分配

- 状态：**完成**（本步用例 6 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/rules.py`：`derange()`（随机洗牌最多 100 次，失败退化为整体旋转兜底）
- `server/state_machine.py`：`start_assign()` 写入 `player.assigned_card_id`、`card.assigned_room_no`，并把 `board_json / submit_cooldown` 归零
- `server/models.py`：`Player.board_json / submit_cooldown` 作为 `draft / cooldown` 的属性别名（规格命名与内部字段同源）
- `tests/test_week2_stepB3_assign.py`：6 条用例（含 2 条纯单元测试）

## 测试

本步新增 **6** 条用例，覆盖本步全部规则断言。

## 已知限制

- 人数 < 2 时无法错位（最低 2 人房间，规则层直接 `CARD_COUNT_MISMATCH`）

## 下一步：B4 阅读阶段

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
