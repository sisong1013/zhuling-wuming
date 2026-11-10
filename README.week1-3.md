# 桌上剧团 · 谁是几号（热座版 · 第 1 周）

多人社交推理小游戏：每个玩家在房间里持有一个**编号**，通过限时提问 / 回答收集线索，
在看板上猜「每个编号对应哪个真人」，**全部猜对立刻获胜**，映射在那一刻才揭晓。

第一周是**热座版**：单进程、纯内存、无数据库、无账号、无断线重连、无 AI。
每个人各自一个浏览器标签页（或同一台机器上的多个浏览器）即可玩。

---

## 1. 环境与安装

- Python 3.10+（本机用 3.11 验证）
- 依赖：`fastapi`、`uvicorn`、`pytest`、`pytest-asyncio`、`websockets`、`httpx`

```bash
cd game
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```

## 2. 启动

```bash
cd game
# Windows
.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# macOS / Linux
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。健康检查：<http://127.0.0.1:8000/healthz>。

## 3. 手动玩一局（2 人即可）

1. **标签页 A**：填昵称（如「阿墨」）→「创建房间（当队长）」→ 记下 6 位房间码。
2. **标签页 B**（另一个窗口，或另一台设备同局域网）：填昵称（如「小北」）+ 房间码 →「加入房间」。
3. 两个标签页的等待室都会实时显示人数（`room:state`）。只有队长能看到「队长配置」和「开始游戏」。
4. 队长可把「回答阶段（每题秒）」调大（如 300）方便慢慢操作 →「保存配置」→「开始游戏」。
5. 开局后每人只看到**自己的编号**和「编号数组 / 昵称数组」，服务端不下发任何映射。
6. **提问阶段**（默认 60s）：每人一次机会 —— 「提问」（选编号 + 输入问题）/「跳过本轮」/「提交看板」。
   - 全员都行动完，立刻提前进入回答阶段。
7. **回答阶段**：被问到的人在自己的界面看到问题卡片，回答后所有人看到 `answer:public`；
   每题 30s，超时记 TIMEOUT（无惩罚）。同一被问者的多道题按队列逐题来，不同人并行。
8. **回放阶段**（30s）：整轮公开问答回放，全员点「确认」或超时后进入下一轮。
9. 任何时候都可以在看板上「保存草稿」；**只有提问阶段**能「提交看板」：
   全对 → 立即 `game:over` 并揭晓完整映射；错了 → 冷却 3 轮（冷却期只能提问/跳过）。
10. 到第 12 轮（可配置）进入**强制提交轮**：只能提交看板，答错（含不完整）罚 1 轮；
    若提交时本身在冷却期，罚 2 轮。

## 4. 目录结构

```
game/
├── server/
│   ├── main.py           # FastAPI 装配：静态页、/healthz、/ws
│   ├── models.py         # 枚举 / GameConfig / Player / Question / Room（含 room:state 输出）
│   ├── rules.py          # 纯规则：房间码、昵称、编号分配、看板判定、冷却、可见性裁剪骨架
│   ├── state_machine.py  # GameRegistry + 阶段状态机（服务端权威）
│   ├── ws_handlers.py    # 连接表 + client→server 消息分发 + 统一错误出口
│   ├── timers.py         # 带 key 的可取消定时器
│   └── static/           # index.html / style.css / app.js（原生 ES Module）
├── tests/
│   ├── conftest.py       # 起真实 uvicorn 子进程
│   ├── helpers.py        # WsClient + 流程封装 + 映射泄露探测器
│   └── test_step1..8*.py # 按 Step 分档的验收测试（共 64 条）
├── scripts/
│   ├── selftest.sh       # 一键自测
│   └── debug_flow.py     # 手工复现脚本（起临时 server，打印每条连接收到的消息）
├── reports/              # step1..step8 + final 报告
├── BLOCKED.md            # 阻塞记录（当前为空）
└── README.md
```

## 5. 协议

### client → server
`room:create{nickname}` · `room:join{roomCode,nickname}` · `game:start{}` · `setup:config{...}` ·
`phase1:ask{targetRoomNo,text}` · `phase1:submit{board}` · `phase1:skip{board?}` ·
`board:saveDraft{board}` · `phase2:answer{questionId,text}` · `phase3:confirm{}` · `ping`

### server → client
`room:created{roomCode,playerId,isCaptain}` · **`room:joined{roomCode,playerId,isCaptain}`**（加入回执，新增）·
`room:state{...}` · `room:error{code,message}` · `game:started{yourRoomNo,roomNos,nicknames}` ·
`phase:changed{phase,round,deadline,...}` · `phase1:progress` · `question:received` · `question:public` ·
`answer:public` · `phase2:nextQuestion` · `phase2:waiting` · `phase2:progress` · `phase3:replay` ·
**`phase3:progress`**（新增）· `submit:result{correct,...}` · `cooldown:updated{playerId,cooldown,reason}` ·
`round:ended{endedRound,nextRound}`（新增）· `game:over{winnerId,fullBoard}` · `error{code,message}` · `pong`

`board` 一律是 `{ "编号": "昵称" }`（值也接受 playerId）。

## 6. 规则实现中的几个口径

- **计时**：服务端权威。只广播 `deadline`（epoch 秒），前端只做倒计时显示。
- **编号**：`assign_room_numbers()` 把 `1..n` 洗牌后按入房顺序发；`game:started.roomNos` 固定升序，
  与 `nicknames` 无位置对应关系；`room:state.players[]` 永远不带编号，只有 `you.roomNo`。
- **冷却**：错误提交后 `cooldown = 3`，**每轮结束 -1**（`cooldown:updated.reason = "round_end"`）。
  按题面直读，实际少 2 次提交机会。
- **强制提交轮**：`round >= forcedSubmitRound`（默认 12）后每一轮都是强制提交轮；
  该轮 `ASK`/`SKIP` 被拒（`FORCED_SUBMIT_REQUIRED`），超时按草稿/空板自动结算。
- **PHASE2**：被问者一人一条队列（队列内串行），队列之间并行；单题独立定时器（key 可取消）。
- **可见性**：第一周只落地 `PUBLIC`；`SEMI` / `PRIVATE` 有枚举 + `rules.clip_text()` 骨架。

## 7. 测试

```bash
cd game
bash scripts/selftest.sh              # 全量
bash scripts/selftest.sh tests/test_step4_phase1.py -x   # 单个文件
```

`scripts/selftest.sh` 会自动挑一个「装了依赖」的解释器（优先 `.venv`，其次 `../.venv`），
并在没有 `bash` 的 Windows 上通过 Git Bash 运行：

```powershell
& "C:\Program Files\Git\bin\bash.exe" -lc "cd '/d/工作区/长期任务/game' && bash scripts/selftest.sh"
```

测试用真实的 uvicorn 子进程 + 真实 WebSocket 客户端（`websockets`），所有等待都带超时。

## 8. 已知限制（第一周范围内）

- 无断线重连：刷新页面 = 离开房间，昵称仍被占用，只能换房间或换昵称重新加入。
- 房间不会回收（进程退出即清空）。
- 一局结束后不能在原房间「再来一局」。
- 无旁观者、无聊天、无私聊；所有问答都是 PUBLIC。
- 无频率限制 / 防刷。
- 全局单进程内存态：多 worker 部署会各自持有不同的房间表。

## 9. 视觉主题（桌上剧团）

站点名：**桌上剧团**（游戏名仍叫「谁是几号」，作为副标保留）。
主题取材于「桌上剧团」四位角色的壁纸（`D:\相册\桌上剧团\`），调色由图片直接取色：

| 角色 | 取到的颜色 | 用在页面的哪里 |
| --- | --- | --- |
| 芙宁娜 | 暖木 `#4a240a / #522c12`、珍珠 `#c3b7ae` | 桌面与地板暖光、主按钮水蓝珠光 `#7fd3e8`、剧院红幕 —— **第一幕 · 讯问** |
| 哥伦比娅 | 梅紫 `#733f56 / #7c556a`、月白 | 剧院内景底色的梅紫余光、白羽纹样 —— **第二幕 · 应答** |
| 桑多涅 | 暗酒红 `#412024`、黄铜、瓷白 `#b6aca7` | 卡片黄铜细线 / 标签旗 / 铆钉点、齿轮纹样 —— **第三幕 · 复述** |
| 沃雅妮莎 | 橄榄金 `#515511`、鼠尾草 `#617c67`、青灰 `#9ab1b2` | 收尾的橄榄金点缀、桂枝纹样 —— **谢幕** |

具体设计语言：

- **底**：深梅紫的剧院内景 + 顶光 + 暖木桌面反光 + 上下酒红丝绒幕（扇形垂边 + 金流苏）。
- **纸**：珍珠纸节目单卡片（左上高光 + 极轻纤维纹），内嵌一圈黄铜细线，四角黄铜藤蔓（内联 SVG）。
- **字**：CJK 衬线（宋体系）做标题、无衬线做正文；标题烫金渐变，品牌铭记是水蓝珍珠球。
- **四幕**：`body[data-phase]` 切换 `--mood` 主色，铜牌光晕、幕次纹样（水波 / 白羽 / 齿轮 / 桂枝）、提示条同步换色。
- **四人徽记**：顶栏一枚四图标小徽（水蓝 / 梅紫 / 黄铜 / 橄榄金），等于把「演员表」摆在剧名旁边。
- **不含**：任何外部字体、图片、框架 —— 全部 CSS + 内联 SVG；壁纸本身没有塞进页面（要的话把某张设成 `body` 背景即可）。

静态预览：`reports/preview/ui-preview.png`（1280 宽整页截图）与可直接打开的 `ui-preview.html`。

---

# 第 2 周：真联机 + 人设卡模式（PERSONA）

## 两种模式

| 模式 | 判定真值 | 终局揭晓 | 前置阶段 |
| --- | --- | --- | --- |
| REAL（默认） | 编号 → 昵称 | game:over.fullBoard | 无（沿用第 1 周） |
| PERSONA | 编号 → 人设卡名 | game:over.reveal[] | CARD_WRITING → READING |

房间对外 status 取值：LOBBY / SETUP / CARD_WRITING / READING / PLAYING / OVER（PHASE1..3 统一报 PLAYING）。

## PERSONA 流程

1. 队长在等待室用 setup:config {gameMode:"PERSONA"} 切模式（只接受 REAL|PERSONA）。
2. game:start → CARD_WRITING：每人 card:submit {name, content}（卡名去空格后 1–20 字、同房间唯一；卡面 ≤300 字）。**不设硬超时。**
3. 全员交齐后，**只有队长**能发 captain:startAssign 触发错位分配（随机洗牌 ≤100 次，失败用旋转兜底；保证 uthor_id ≠ 自己）。
4. READING（默认 180s，可配 
eadingSeconds）：每人单独收到 persona:assigned，含本人编号、卡面、**打乱顺序**的卡名表；**不下发任何卡→作者/编号映射**。全员 
eading:confirm 或超时 → 第一幕。
5. 三阶段循环、冷却（错 3 轮，每轮 -1）、第 12 轮强制提交：与第 1 周**完全一致**。
6. 看板填 {编号: 卡名}；自己那格是白送。全对 → game:over{reveal:[{roomNo,cardName,cardContent,authorNickname}]}。

## 回答的软约束（重要）

阶段二作答**应当**贴合自己拿到的角色语气，但这是**玩家自觉约束**：
服务端不做任何「是否符合人设」的判断，只校验非空与长度，文本原样存储、原样广播。
唯一的作用是社交推理——答得不像，别人就会猜错人。

## 真联机要点

- 多房间并存：GameRegistry.rooms: dict[roomCode, Room]，房间码全局唯一，互不干扰。
- 断线重连：入座签发 
econnectToken（随 
oom:state.you.reconnectToken 私发），前端存 localStorage；
  重连用 conn:reconnect {roomCode, playerId, token}，成功回 
econnect:ok{snapshot}（当前阶段完整快照），失败回 
econnect:failed{code}。
- 断线**保留座位**（connected=0），不踢人；online_players 只算在线者，掉线玩家不阻塞「全员行动/全员确认」。
- 心跳：前端每 20s ping → 服务端回 pong；服务端超过 heartbeatSeconds（默认 60s）没收到任何消息即判掉线。
- 生命周期：OVER 后房间保留 overRetentionSeconds（默认 10 分钟）可复盘，之后回收（重连会得到 RECONNECT_INVALID）。

## AI 接口（第 3 周接 LLM）

server/ai.py：generate_ai_card() -> {name, content}、i_answer_as_persona(card, question) -> str 目前是确定性占位。
AI 玩家（captain:addAi {nickname}）与真人**完全同构**：也写卡、也参与错位分配（只校验 uthor_id ≠ 自己）、本幕自动放弃、被问时自动作答。
第 3 周只需替换这两个函数实现，调用方不用改。

## 一键自测

`ash
bash scripts/selftest.sh
`
第 1 周 64 条 + 第 2 周 64 条 = **128 passed**。

---

# 第 3 周：人机混战（AI 玩家）

## 加 AI 进来

等待室（团长台）新增两行：

- **玩法**：`猜真人` / `人设卡`（对应 `setup:config {gameMode}`）
- **陪演（AI）**：`+1 AI` / `+2 AI` → 事件 `room:addAI {count}`

AI 角色从预设名池取（星辉剑士、折纸诗人、紫电琴师…），`isAi=true`、`connected=1`；
它们**走和真人一模一样的校验路径**（冷却、强制轮、阶段、错误码），没有特权。

## AI 会做什么

| 阶段 | AI 行为 | 节奏 |
| --- | --- | --- |
| `CARD_WRITING` | LLM 写一张人设卡（不合法就退回离线池），撞名自动加序号 | 2s 后提交 |
| `READING` | 视为已示意（不阻塞全员门槛） | 立即 |
| `PHASE1` | `ASK / SUBMIT / SKIP`（JSON 决策），冷却中强制 `SKIP`，强制轮直接交看板 | 5–10s 随机 |
| `PHASE2` | 按自己拿到的人设卡作答（第一人称、可以撒谎、不报编号） | 按字数 2–5s |
| `PHASE3` | 自动确认回放 | 1–3s |

## 防作弊

AI 的 Prompt 只含：自己的编号、自己拿到的卡、**公开**问答历史、全场卡名/昵称表、可选目标**编号**。
永不注入「编号 → 真人 / 编号 → 卡」映射；测试用「同一行不得同时出现某人编号与昵称」做结构扫描。

## 接 LLM（可选）

```bash
cd game
cp env.example .env      # 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
```

OpenAI 兼容即可；默认 `gpt-4o-mini`。**不配也能玩**——AI 走确定性兜底，绝不卡局。
超时 15s、任何异常都返回兜底文案。

## 调试口

`GET /debug/ai`（需 `AI_DEBUG=1`）：LLM 状态、每个 AI 的最近 Prompt/决策/看板、房间真值（仅供自动化）。

## 测试

```bash
bash scripts/selftest.sh
```
第 1 周 64 + 第 2 周 64 + 第 3 周 35 = **163 passed**。
