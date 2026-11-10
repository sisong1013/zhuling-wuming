# 第 2 周 · Step A2：断线重连 / 保留座位 / 心跳

- 状态：**完成**（本步用例 7 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/models.py`：`Player.reconnect_token`、`Room.active_players()`（只看在线，全掉线退回全部避免死锁）
- `server/state_machine.py`：`register_session / unregister_session / touch_session`、`snapshot_for()`、`reconnect()`、`start_watchdog()`（每 2s 扫描，超过 `heartbeat_seconds` 判掉线）
- `server/ws_handlers.py`：新增 `conn:reconnect`（成功回 `reconnect:ok{snapshot}`，失败回 `reconnect:failed{code}`）；`dispatch` 对任何消息刷新心跳；建房/加入注册会话
- `server/main.py`：lifespan 启停看门狗，断连时注销会话
- `tests/test_week2_stepA2_reconnect.py`：7 条用例

## 测试

本步新增 **7** 条用例，覆盖本步全部规则断言。

## 已知限制

- 心跳阈值可配（`heartbeatSeconds`，测试压到 1s）；生产默认 60s
- 掉线玩家不阻塞「全员行动/确认」，但仍在座位与名册中；不发踢人逻辑

## 下一步：A3 room:state 契约

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
