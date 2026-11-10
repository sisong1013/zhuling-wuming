/* app.js —— 入口：把 ws 事件分发给对应视图模块，负责布局切换
 *
 * 原则：这里不做业务判断，只根据 state.phase 选视图、更新轻量片段。
 */

import { $, esc, toast } from "./js/ui.js";
import { state, connect, on, send, hardReset } from "./js/ws.js";
import { mountTimer, renderTimer, startTicker } from "./js/timer.js";
import { bindBoardContext, renderBoard, toggleBoard } from "./js/board.js";
import { renderLobby } from "./js/lobby.js";
import { renderWaiting } from "./js/waiting.js";
import { renderCard } from "./js/card.js";
import { renderReading } from "./js/reading.js";
import { renderPhase1 } from "./js/phase1.js";
import { renderPhase2 } from "./js/phase2.js";
import { renderPhase3 } from "./js/phase3.js";
import { renderOver } from "./js/over.js";

const PHASE_LABEL = {
  LOBBY: "候场",
  SETUP: "开演前",
  CARD_WRITING: "写卡",
  READING: "读卡",
  PHASE1: "第一幕 · 讯问",
  PHASE2: "第二幕 · 应答",
  PHASE3: "第三幕 · 复述",
  OVER: "谢幕",
};

const ctx = { send, reset: restart };
let mountedKey = "";

function currentView() {
  if (!state.playerId) return "lobby";
  switch (state.phase) {
    case "LOBBY":
    case "SETUP":
      return "waiting";
    case "CARD_WRITING":
      return "card";
    case "READING":
      return "reading";
    case "PHASE1":
      return "phase1";
    case "PHASE2":
      return "phase2";
    case "PHASE3":
      return "phase3";
    case "OVER":
      return "over";
    default:
      return "waiting";
  }
}

const RENDERERS = {
  lobby: renderLobby,
  waiting: renderWaiting,
  card: renderCard,
  reading: renderReading,
  phase1: renderPhase1,
  phase2: renderPhase2,
  phase3: renderPhase3,
  over: renderOver,
};

const IN_GAME = new Set(["phase1", "phase2", "phase3", "card", "reading"]);

function render(force = false) {
  document.body.dataset.phase = state.phase;
  const view = currentView();
  const root = $("#view");
  const side = $("#side");
  const roster = (state.players || [])
    .map((p) => `${p.id}:${p.nickname}:${p.isAi ? 1 : 0}:${p.connected ? 1 : 0}`)
    .join(",");
  const key = [
    view,
    state.phase,
    state.round,
    state.count,
    state.gameMode,  // 团长切玩法要立刻看到选中态
    state.yourId || (state.you && state.you.isCaptain ? "cap" : "-"),
    roster,
    state.cardSubmitted ? "c1" : "c0",
    state.readingConfirmed ? "r1" : "r0",
    state.currentQuestion ? state.currentQuestion.questionId : "-",
    (state.replay || []).length,
    state.phase === "OVER" ? (state.over && state.over.winnerId) || "-" : "-",
  ].join("|");

  if (force || key !== mountedKey) {
    const keepValues = snapshotInputs(root);
    mountedKey = key;
    if (RENDERERS[view]) RENDERERS[view](root, state, ctx);
    restoreInputs(root, keepValues);
  } else {
    patchHints();
  }

  const showSide = IN_GAME.has(view) || view === "over";
  if (side) side.hidden = !showSide;
  const layout = document.querySelector(".layout");
  if (layout) layout.classList.toggle("is-single", !showSide);
  bindBoardContext(state, ctx);
  renderHud();
  renderFeed();
  renderRoster();
  const drawer = $("#board");
  if (state.phase === "PHASE1" && drawer && !drawer.hidden) {
    renderBoard(drawer, state, ctx);
  }
  if (state.phase === "OVER") toggleBoard(false);
}


/** 重绘前记下用户正在输入的框，重绘后回填（避免打字被冲掉） */
function snapshotInputs(root) {
  const out = {};
  if (!root) return out;
  root.querySelectorAll("input, textarea").forEach((el) => {
    if (el.id && !el.disabled) out[el.id] = el.value;
  });
  return out;
}

function restoreInputs(root, values) {
  if (!root) return;
  for (const [id, value] of Object.entries(values)) {
    const el = root.querySelector(`#${id}`);
    if (el && !el.value && !el.disabled) el.value = value;
  }
}

/** 视图重渲染太贵（会打断输入），只有这些小片段需要随时刷新 */
function patchHints() {
  const cards = state.cards || {};
  if (state.phase === "CARD_WRITING") {
    const cardHint = document.getElementById("card-hint");
    if (cardHint) {
      const total = cards.total ?? state.count;
      const done = cards.submitted ?? 0;
      cardHint.textContent =
        done >= total && total > 0
          ? `全员已交齐（${done}/${total}）`
          : `已交 ${done}/${total} 张卡`;
    }
    const assign = document.getElementById("btn-start-assign");
    if (assign) assign.disabled = (cards.submitted ?? 0) < (cards.total ?? state.count);
  }

  if (state.phase === "READING") {
    const prog = state.readingProgress || {};
    const hints = document.querySelectorAll("#view .hint");
    const last = hints[hints.length - 1];
    if (last && prog.total) last.textContent = `${prog.confirmed}/${prog.total} 人读完了`;
  }

  if (state.phase === "PHASE1") {
    const chips = document.querySelectorAll("#view .progress-chips .chip");
    state.players.forEach((p, i) => {
      if (chips[i]) chips[i].classList.toggle("done", state.progress.acted.includes(p.id));
    });
  }
}

function renderHud() {
  const hud = $("#hud");
  if (!hud) return;
  hud.hidden = !state.playerId;
  const myNo = $("#my-no");
  if (myNo) myNo.textContent = state.myRoomNo ?? state.you.roomNo ?? "—";
  const phaseEl = $("#phase-name");
  if (phaseEl) phaseEl.textContent = PHASE_LABEL[state.phase] || state.phase;
  const roundEl = $("#round-no");
  if (roundEl) roundEl.textContent = state.round || "—";
  renderTimer(mountTimer($("#timer")), state);
}

function renderFeed() {
  const list = $("#feed");
  if (!list) return;
  list.innerHTML = (state.feed || [])
    .slice(-40)
    .map(
      (item) =>
        `<li class="feed-item ${esc(item.kind || "a")}"><span class="feed-text">${esc(
          item.text
        )}</span></li>`
    )
    .join("");
  list.scrollTop = list.scrollHeight;
}

function renderRoster() {
  const list = $("#roster");
  if (!list || !state.players) return;
  list.innerHTML = state.players
    .map((p) => {
      const tags = [];
      if (p.isCaptain) tags.push('<span class="tag">队长</span>');
      if (p.isAi) tags.push('<span class="tag ai">AI</span>');
      if (p.id === state.you.id) tags.push('<span class="tag self">你</span>');
      if (p.cooldown > 0) tags.push(`<span class="tag cool">冷却 ${p.cooldown}</span>`);
      if (state.aiThinking[p.id]) {
        const label =
          { write_card: "写卡中", phase1: "思考中", answer: "作答中" }[state.aiThinking[p.id]] ||
          "思考中";
        tags.push(`<span class="tag think">${label}</span>`);
      }
      if (!p.connected) tags.push('<span class="tag off">掉线</span>');
      return `<li class="player-item${p.connected ? "" : " is-offline"}">
        <span class="who">${esc(p.nickname)}</span>${tags.join("")}</li>`;
    })
    .join("");
}

function restart() {
  // 彻底离开：清本地状态 + 断开旧连接（服务端座位随连接断开而释放）
  hardReset();
  mountedKey = "";
  toggleBoard(false);
  location.replace(location.pathname);
}

function boot() {
  const openBtn = $("#btn-open-board");
  if (openBtn) openBtn.addEventListener("click", () => toggleBoard());
  const leaveBtn = $("#btn-leave");
  if (leaveBtn) {
    leaveBtn.addEventListener("click", () => {
      if (!confirm("确认离开？座位会被释放")) return;
      restart();
      toast("已回到入口");
    });
  }

  on("state", () => render());
  on("feed", () => {
    renderFeed();
    renderRoster();
  });
  on("over", () => {
    mountedKey = "";
    render(true);
  });
  on("connection", ({ connected }) => {
    if (!connected) toast("连接断开，正在重连…", "error");
  });

  startTicker(
    () => state,
    () => $("#timer")
  );

  connect();
  render(true);
}

boot();
