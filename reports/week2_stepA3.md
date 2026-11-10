# 第 2 周 · Step A3：room:state 广播契约

- 状态：**完成**（本步用例 5 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/models.py`：`Room.to_state()` 增加 `status / gameMode / visibility`，`you` 增加 `reconnectToken / cardSubmitted / readingConfirmed`；PERSONA 模式附带 `cards:{submitted,assigned}`
- `server/models.py`：`Player.public_view()` 继续只给 `id/nickname/isCaptain/connected`（绝不下发别人的编号）
- `tests/test_week2_stepA3_state.py`：5 条用例

## 测试

本步新增 **5** 条用例，覆盖本步全部规则断言。

## 已知限制

- `room:state` 是全量快照，未做增量 diff（8 人上限下负载可忽略）

## 下一步：B1 模式选择

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
