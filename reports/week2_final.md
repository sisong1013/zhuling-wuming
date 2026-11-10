# 第 2 周交付报告（真联机 + 人设卡模式）

> 状态：**全部 Step 完成，无 BLOCKED**。
> 全量自动验收：`bash scripts/selftest.sh` → **128 passed**（第 1 周 64 + 第 2 周 64），退出码 0。

---

## 1. 启动命令

```bash
cd game
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # 首次
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000/
```

一键自测：

```bash
bash scripts/selftest.sh                # 全量
bash scripts/selftest.sh tests/test_week2_stepB4_reading.py   # 单步
```

无人值守巡检（本轮就是这么跑的）：改代码 → `bash scripts/selftest.sh` → 失败读栈 → 改 → 重跑，最多 5 轮/步。

---

## 2. 玩法一：REAL（猜真人）一局

1. 甲打开页面 →「创建房间」，得到 6 位房间码（同时拿到 `reconnectToken`）。
2. 乙/丙用房间码加入，各自填昵称。
3. 甲（队长）在团长台可选 `gameMode = REAL`（默认），点「开始游戏」。
4. 服务端把编号随机分配，每人只收到自己的 `yourRoomNo`；进入**第一幕 · 讯问**（60s）。
5. 每人每轮一次机会：讯问某人 / 呈上看板 / 略过。被问者立刻收到问题，24 小时内（可配 30s）作答。
6. 全员行动完 → **第二幕 · 应答** → **第三幕 · 复述**（30s 回放确认）→ 下一轮。
7. 提交看板全对 → 立刻 `game:over{fullBoard}`，终局才揭晓「编号 → 昵称」。
8. 第 12 轮（可配 `forcedSubmitRound`）强制全员提交。

## 3. 玩法二：PERSONA（人设卡）一局

1. 甲建房、乙/丙加入（队长也可用「添加 AI」塞一个木偶玩家进来练手）。
2. 队长把模式切成 **PERSONA** → 开始游戏。
3. **写卡阶段（无硬超时）**：每人提交 `{name, content}`，卡名 1–20 字且同房间唯一，卡面 ≤300 字。广播 `card:progress{submitted,total}`。
4. 全员交齐 → **队长**发 `captain:startAssign` 触发**错位分配**（保证每人拿到的卡 `author_id ≠ 自己`；随机洗牌 + 旋转兜底）。
5. **阅读阶段（默认 180s）**：每人单独收到 `persona:assigned`（本人编号、卡面、打乱的卡名表、deadline），**不含任何卡→作者/编号映射**。全员 `reading:confirm` 或超时 → 进入轮次。
6. **第一幕 · 讯问**：提问/看板/略过，规则与 REAL 完全一致（冷却 3 轮、每轮 -1、第 12 轮强制提交都不变）。
   - 看板内容是 `{编号: 卡名}`；自己那格是白送（自己当然知道自己的卡名）。
   - 作答时**应尽量贴合所拿卡的语气，但服务端不判定**，只做长度/空值校验，文本原样广播。
7. 看板全对 → `game:over{reveal:[{roomNo, cardName, cardContent, authorNickname}]}`，揭晓「哪张卡是谁写的」。

---

## 4. 全部测试结果

| 文件 | 用例数 | 结果 |
| --- | --- | --- |
| `tests/test_step1..step8`（第 1 周） | 64 | ✅ 全绿（无回归） |
| `test_week2_stepA1_rooms.py` 多房间 + 生命周期 | 6 | ✅ |
| `test_week2_stepA2_reconnect.py` 重连 + 心跳 + 在线门槛 | 7 | ✅ |
| `test_week2_stepA3_state.py` `room:state` 契约 | 5 | ✅ |
| `test_week2_stepB1_mode.py` 模式选择 | 6 | ✅ |
| `test_week2_stepB2_cards.py` 写卡规则 | 10 | ✅ |
| `test_week2_stepB3_assign.py` 错位分配 | 6 | ✅ |
| `test_week2_stepB4_reading.py` 阅读阶段 | 7 | ✅ |
| `test_week2_stepB5_judge.py` 判定与揭晓 | 5 | ✅ |
| `test_week2_stepB6_softconstraint.py` 回答软约束 | 4 | ✅ |
| `test_week2_stepB7_ai.py` AI 接口预留 | 8 | ✅ |
| **合计** | **128** | ✅ 128 passed / 0 failed |

没有 xfail、没有 skip、没有删除或弱化任何断言。

---

## 5. 新增/变更的 WebSocket 事件

client → server：`conn:reconnect {roomCode, playerId, token}`、`card:submit {name, content}`、`captain:startAssign {}`、`reading:confirm {}`、`captain:addAi {nickname}`（B7 占位）、`ping`。

server → client：`room:state`（+`status/gameMode/visibility/cards`、`you.reconnectToken`）、`reconnect:ok {snapshot}`、`reconnect:failed {code}`、`card:progress`、`card:submitted`、`persona:assigned`、`reading:progress`、`game:over`（PERSONA 带 `reveal`）。

## 6. 数据模型变更

- `Room`：`game_mode`、`visibility`、`cards: list[PersonaCard]`、`card_submitted: set`、`assigned: bool`、`finished_at`
- `Player`：`reconnect_token`、`card_submitted`、`assigned_card_id`、`reading_confirmed`、`is_ai`（+ `board_json` / `submit_cooldown` 别名）
- 新 `PersonaCard`：`id / game_id / author_id / name / content / assigned_room_no`
- `GameConfig` 新增：`reading_seconds`(180)、`heartbeat_seconds`(60)、`over_retention_seconds`(600)
- `Phase` 新增：`SETUP / CARD_WRITING / READING`；对外 `status`：`PHASE1..3 → PLAYING`

## 7. BLOCKED 项

**无。** 10 个 Step 全部一次或数次自愈通过，`BLOCKED.md` 未新增条目。

## 8. 已知限制

1. 房间与座位仍是**单进程内存**；重启即全部丢失（纯内存设计前提，符合任务约束）。
2. 多进程/多实例部署需要共享层（Redis 等）——第 3 周或更后面再说，本周明确不做。
3. 写入的卡只做长度/唯一性校验，不做内容审核（含敏感词），也没有「撤回已交卡」。
4. `room:state` 全量广播，无增量 diff；8 人上限下可忽略。
5. AI 玩家是占位：只会「放弃本幕」和一句套模板回答，不接 LLM。
6. 前端尚未实现 PERSONA 的写卡/阅读界面（本轮交付集中服务端规则 + 测试；界面原型见 `game/prototype/index.html`，已预留 `编号 → 卡名 / 人设卡模式` 文案切换）。

## 9. 第 3 周待办

1. **接 LLM**：把 `server/ai.py` 的两个 stub 换成真实调用（写卡 + 按卡作答），保持函数签名不变。
2. **PERSONA 前端**：写卡表单（卡名唯一性即时提示）、阅读阶段卡面展示、看板改成「选卡名」下拉、谢幕 reveal 列表。
3. **重连体验**：前端 localStorage 存 token、断线自动重连 + 顶部「重连中」状态条。
4. **可观测性**：房间列表 `/admin/rooms`（只读）、结构化日志、连麦测试。
5. **安全**：昵称/卡名/回答的敏感词与频控；`conn:reconnect` 加简单限流防爆破。
6. **规模化**：把 `GameRegistry` 换成可注入的存储接口，为多实例做准备。
