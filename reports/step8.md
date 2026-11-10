# Step 8 报告 · 非法操作与错误码

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/tests/test_step8_errors.py` | Step 8 验收测试（12 条） |
| `game/server/ws_handlers.py` | 统一错误出口（本轮复核，未再改动逻辑）：`GameError` → `error{code,message,for}`；建房/进房失败走 `room:error` |

## 错误码一览（服务端所有拒绝都带 code + message）
| code | 触发 |
| --- | --- |
| `BAD_JSON` / `INVALID_PAYLOAD` / `UNKNOWN_TYPE` | 消息格式错误、字段非法、未知消息类型 |
| `NOT_IN_ROOM` | 还没建房/加入就发游戏动作 |
| `ALREADY_IN_ROOM` | 同一条连接二次建房/加入 |
| `ROOM_NOT_FOUND` / `ROOM_ALREADY_STARTED` / `ROOM_FULL` / `NICKNAME_TAKEN` / `NICKNAME_INVALID` | 加入校验 |
| `NOT_CAPTAIN` | 非队长 `game:start` / `setup:config` |
| `NOT_ENOUGH_PLAYERS` | 人数不足开局 |
| `WRONG_PHASE` | 当前阶段不允许该动作（含结束后的一切动作） |
| `ALREADY_ACTED` | 同一轮第二次 PHASE1 行动 |
| `ALREADY_CONFIRMED` | 同一轮回放重复确认 |
| `PLAYER_IN_COOLDOWN` | 冷却期提交看板 |
| `FORCED_SUBMIT_REQUIRED` | 强制提交轮里 ASK / SKIP |
| `INVALID_TARGET` | 提问目标不存在 / 问自己 / 目标不是数字 |
| `QUESTION_NOT_FOUND` / `NOT_YOUR_QUESTION` / `ALREADY_ANSWERED` | 作答校验 |
| `INVALID_CONFIG` | 配置超范围或未知字段 |

**校验顺序**（每个 handler 都一样）：身份 → 房间/阶段 → 权限 → 重复动作 → 载荷。

## 测试结果
```
64 passed in 47.46s   # 全量：Step1(6)+Step2(10)+Step3(7)+Step4(10)+Step5(6)+Step6(7)+Step7(6)+Step8(12)
```
Step 8 断言：
- 等待室里 `phase1:ask/submit/skip`、`phase2:answer`、`phase3:confirm`、`board:saveDraft` 全部 `WRONG_PHASE`
- PHASE1 里答题/确认 → `WRONG_PHASE`；PHASE3 里提问/提交/补答 → `WRONG_PHASE`
- 同轮重复 `skip`、重复 `ask`、重复 `submit` → `ALREADY_ACTED`；重复 `phase3:confirm` → `ALREADY_CONFIRMED`
- 非队长 `setup:config` → `NOT_CAPTAIN`；队长开局后改配置 → `WRONG_PHASE`
- 配置越界（`phase1Seconds=9999`、`maxPlayers=99`）与未知字段 → `INVALID_CONFIG`
- 第 9 人加入 8 人房 → `room:error ROOM_FULL`；`maxPlayers=2` 时第 3 人被拒
- 未进房发任何游戏动作 → `NOT_IN_ROOM`
- 非法载荷（目标非数字 / 空问题 / 看板不是对象 / 看板键非数字 / 草稿是数组）全部被拒，且**不消耗行动机会**
- 冷却期玩家：提交 → `PLAYER_IN_COOLDOWN`，但 `skip` 仍然成功

## 当前限制
- 错误消息里的 `for` 字段记录触发它的消息类型，方便前端定位，但不是协议必需字段。
- 没有做「同 IP 频率限制」之类的防刷（第一周不做）。

## 下一步
收尾：`reports/final.md`、`README.md`、`BLOCKED.md`。
