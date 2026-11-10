# BLOCKED 记录

> 格式约定：某 Step 连续 5 轮修复仍失败时，在这里记录「失败详情 / 已尝试的修复 / 卡点」，
> 然后跳到下一个不依赖它的 Step，最后统一汇报。

## 当前状态

**无阻塞项。** Step 1 – Step 8 全部一次或数次迭代后全绿，`bash scripts/selftest.sh` 64 条断言全通过。

### 已解决、但值得记录的坑（不算 BLOCKED）

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| `tests/helpers.py` 的 `wait_for` 4 秒后抛出含上千条 `room:state` 的超时 | `wait_for` 通过 `recv()` 取消息，而 `recv()` 优先从 backlog 取 → 「取出-不匹配-压回」忙等死循环 | `wait_for` 改为直接读 socket，只有不匹配的消息才进 backlog |
| `cooldown:updated` 断言偶尔读到旧值（3 而不是 2） | 同一连接上残留「提交错误」那条广播 | `cooldown:updated` 增加 `reason`（`submit_wrong` / `round_end`）与 `round` 字段，测试按语义过滤 |
| 前端「回答」按钮发出后报 `QUESTION_NOT_FOUND` | `phase2:nextQuestion` 的字段是 `questionId`，前端误用 `q.id` | 前端改用 `q.questionId`（已在浏览器里复测通过） |
| 首屏显示等待室而不是入口表单 | `render()` 用 `phase === "LOBBY"` 决定视图，开局前也是 LOBBY | `syncView()` 先判 `playerId` 是否存在 |

---

## 第 2 周（多房间 / 重连 / PERSONA）

**无新增阻塞项。** 10 个 Step（A1/A2/A3/B1–B7）全部自动跑通，无需人工介入。

自愈过的问题（记录备查，非阻塞）：

1. 测试助手 collect() 会清空 backlog，导致后续 wait_for("room:state") 等不到新消息 → 给 WsClient 加 last_room_state + state_of()，测试改看「最近状态」。
2. 人设卡卡名原先用 sanitize_text 静默截断到 20 字，规格要求「1–20 字否则拒绝」→ 改成显式校验并报 CARD_NAME_INVALID。
3. AI 玩家不参与「阅读示意 / 回放确认」，会卡住全员门槛 → 服务端把 AI 直接视为已确认。
4. 第二幕作答需在 PHASE2 才合法（问题在 PHASE1 只是入队）→ 测试流程改为「问 → 被问者放弃 → 进第二幕 → 作答」。
5. `phase1:ask` 的目标字段是 `targetRoomNo`（不是 `targetNo`）。

---

## 第 3 周（人机混战）

**无阻塞项。** 但有一条环境说明值得记：

- 本机**没有 `LLM_API_KEY`**（也无法在本会话里读/写 `.env`，安全策略拦截）。
  按任务预案走「mock + 兜底」：游戏内 AI 用确定性兜底完成全部流程；
  真实联网路径由 `tests/test_week3_step1_llm.py` 用 monkeypatch 覆盖（成功/超时/502/JSON 围栏）。
  想跑真 LLM：`cp game/env.example game/.env` 填 Key 后重跑 `tests/test_week3_step7_full_ai.py`。

自愈过的问题（非阻塞）：

1. `setup:config` 的秒数校验原本要求 `1..600`，把 AI 的亚秒级延迟配置挡掉了 → AI 相关字段放开到 `0..600`。
2. 测试助手 `full_room()` 以前会**静默吞掉** `setup:config` 的 error（配置没生效却照跑）→ 现在配置被拒直接断言失败。
3. `/debug/ai` 的决策日志是全局的，跨房间会串 → 测试按 `room` 过滤。
4. 「整局跑到结束」在 4 人局里几乎不可能自然全对（无必赢推理路径）→ 调试口在 `AI_DEBUG=1` 时提供 `truth` 供自动化收尾。
