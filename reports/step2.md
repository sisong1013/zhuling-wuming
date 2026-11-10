# Step 2 报告 · 房间码与等待室

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/models.py` | 新增：`Phase` / `Visibility` / `QuestionStatus` / `ActionKind` 枚举、`GameError`、`GameConfig`（带校验的补丁）、`Player`、`Question`、`Room`（含 `to_state()` 私有化输出） |
| `game/server/rules.py` | 纯函数层：昵称清洗、6 位房间码生成（唯一）、编号分配、看板规范化/判定、冷却计算、可见性裁剪骨架 |
| `game/server/state_machine.py` | `GameRegistry`：建房、加入、断线标记、按人广播 `room:state`、队长改配置 |
| `game/server/ws_handlers.py` | `ConnectionHub`（playerId→WebSocket）、`Session`、消息分发表、统一 `room:error` / `error` 出口 |
| `game/server/main.py` | 装配 `HUB` + `REGISTRY`，WS 循环走 `ws_handlers.dispatch`，断线时标记 offline 并广播 |
| `game/server/__init__.py` | 让 `server` 成为包（uvicorn 的 `server.main:app` 相对导入） |
| `game/tests/test_step2_rooms.py` | Step 2 验收测试（10 条） |

## 规则落地
- 建房：生成 6 位数字房间码，**全局唯一**（内存查重，最多 2000 次）；创建者 `isCaptain=true`。
- 加入校验顺序：房间码存在 → 未开始 → 人数 < maxPlayers(8) → 昵称同房间唯一 → 昵称本身合法。
- 失败一律回 `room:error{code,message}`：`ROOM_NOT_FOUND` / `ROOM_ALREADY_STARTED` / `ROOM_FULL` / `NICKNAME_TAKEN` / `NICKNAME_INVALID`。
- `room:state` 对每个人单独生成（`Room.to_state(viewer)`），里面**没有**编号映射；开局前 `you.roomNo` 为 `null`。
- `onlineCount` 只统计 `connected` 的玩家；断线后广播一次新的 `room:state`。
- `setup:config` 已实现（队长 + 仅等待室 + 范围校验），Step 8 会正式断言权限。

## 测试结果
```
16 passed in 1.98s   # Step1(6) + Step2(10)
```
Step 2 断言：
- 建房拿 6 位数字码、`isCaptain=True`
- 连开 6 个房间码互不相同
- 3 人加入后**所有 4 条连接**收到 `count=4` / `onlineCount=4` / `phase=LOBBY` 且 `players` 无 `roomNo`
- 重复昵称 → `NICKNAME_TAKEN`，房间人数不变
- 错误房间码 → `ROOM_NOT_FOUND`
- 空昵称 → `NICKNAME_INVALID`
- 加入方拿到 `playerId` 且 `isCaptain=false`
- 断线后 `connected=false`、`onlineCount` 减 1
- 同一条连接二次建房 → `ALREADY_IN_ROOM`
- 队长改配置成功并广播

## 当前限制
- 房间不会因为全员离开而回收（第一周纯内存、进程退出即清空）。
- 没有断线重连：断线即 `connected=false`，重连要重新加入（且旧昵称仍占用 → `NICKNAME_TAKEN`）。
- SEMI / PRIVATE 只有枚举与 `rules.clip_text` 骨架。

## 下一步
Step 3：`game:start` —— 随机编号、逐人下发 `game:started`、永不下发映射。
