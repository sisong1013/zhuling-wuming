/* ws.js —— 唯一的网络层：连接、重连、心跳、事件总线、状态仓库
 *
 * 前端不维护业务规则：所有状态都来自服务端事件，视图只读 state。
 */

import { toast } from "./ui.js";

// 按「标签页」隔离：localStorage 会让新标签页抢走上一个标签页的座位
const TOKEN_KEY = "zhuoshang:reconnect";
const store = window.sessionStorage;

export const state = {
  connected: false,
  playerId: null,
  roomCode: null,
  nickname: "",
  isCaptain: false,
  phase: "LOBBY",
  status: "NEW",
  gameMode: "REAL",
  round: 0,
  deadline: null,
  forcedSubmit: false,
  count: 0,
  maxPlayers: 8,
  players: [],
  you: {},
  board: {},
  feed: [],
  progress: { acted: [], total: 0 },
  cardNames: [],
  yourCard: null,
  cards: { submitted: 0, total: 0 },
  cardSubmitted: false,
  readingConfirmed: false,
  readingProgress: { confirmed: 0, total: 0 },
  currentQuestion: null,
  replay: [],
  over: null,
  config: null,
  myRoomNo: null,
  roomNos: [],
  nicknames: [],
  aiThinking: {},
};

const listeners = new Map(); // event → Set<fn>
let socket = null;
let heartbeat = null;
let reconnectTimer = null;

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

export function emit(event, payload) {
  for (const fn of listeners.get(event) || []) {
    try {
      fn(payload);
    } catch (err) {
      console.error(`[ws] 处理 ${event} 出错`, err);
    }
  }
}

export function send(type, payload = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    toast("还没连上服务端", "error");
    return false;
  }
  socket.send(JSON.stringify({ type, ...payload }));
  return true;
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

export function setConn(text, ok) {
  const el = document.getElementById("conn");
  if (!el) return;
  el.textContent = text;
  el.dataset.state = ok ? "on" : "off";
}

export function connect() {
  clearTimeout(reconnectTimer);
  try {
    socket = new WebSocket(wsUrl());
  } catch (err) {
    setConn("连接失败", false);
    reconnectTimer = setTimeout(connect, 2000);
    return;
  }

  socket.addEventListener("open", () => {
    state.connected = true;
    setConn("已连接", true);
    startHeartbeat();
    tryResume();
    emit("connection", { connected: true });
  });

  socket.addEventListener("close", () => {
    state.connected = false;
    setConn("重连中…", false);
    stopHeartbeat();
    emit("connection", { connected: false });
    reconnectTimer = setTimeout(connect, 1500);
  });

  socket.addEventListener("message", (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    receive(msg);
  });
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeat = setInterval(() => send("ping", { t: Date.now() }), 20000);
}

function stopHeartbeat() {
  if (heartbeat) clearInterval(heartbeat);
  heartbeat = null;
}

/* ------------------------------------------------------------------ */
/* 事件 → 状态                                                         */
/* ------------------------------------------------------------------ */

function receive(msg) {
  const type = msg.type;
  if (type === "pong") return;

  if (type === "error" || type === "room:error") {
    toast(msg.message || msg.code || "出错了", "error");
    emit("error", msg);
    return;
  }

  if (type === "room:created" || type === "room:joined") {
    state.playerId = msg.playerId;
    state.roomCode = msg.roomCode;
    state.nickname = msg.nickname;
    state.isCaptain = !!msg.isCaptain;
    state.status = "LOBBY";
    rememberToken();
    emit("room:entered", msg);
    return;
  }

  if (type === "room:state") {
    state.roomCode = msg.roomCode;
    state.phase = msg.phase;
    state.status = msg.status || msg.phase;
    state.gameMode = msg.gameMode || state.gameMode;
    state.round = msg.round;
    state.deadline = msg.deadline ?? null;
    state.forcedSubmit = !!msg.forcedSubmit;
    state.count = msg.count;
    state.maxPlayers = msg.maxPlayers;
    state.players = msg.players || [];
    state.config = msg.config || state.config;
    if (msg.cards) state.cards = { ...state.cards, ...msg.cards };
    if (msg.you) {
      state.you = msg.you;
      if (msg.you.roomNo != null) state.myRoomNo = msg.you.roomNo;
      // 只在本地没有选择时才回填服务端草稿，避免把正在选的冲掉
      if (msg.you.draft !== undefined) {
        const local = state.board || {};
        const hasLocal = Object.keys(local).some((k) => local[k]);
        if (!hasLocal) state.board = { ...(msg.you.draft || {}) };
      }
      if (msg.you.cardSubmitted != null) state.cardSubmitted = !!msg.you.cardSubmitted;
      if (msg.you.readingConfirmed != null) state.readingConfirmed = !!msg.you.readingConfirmed;
      if (msg.you.reconnectToken) saveToken(msg.roomCode, msg.you.id, msg.you.reconnectToken);
    }
    if (msg.winnerId) state.winnerId = msg.winnerId;
    emit("state", state);
    return;
  }

  if (type === "game:started") {
    state.myRoomNo = msg.yourRoomNo;
    state.you.roomNo = msg.yourRoomNo;
    state.roomNos = msg.roomNos || [];
    state.nicknames = msg.nicknames || [];
    state.board = {};
    state.feed = [];
    emit("state", state);
    return;
  }

  if (type === "phase:changed") {
    const prevRound = state.round;
    state.phase = msg.phase;
    state.status = msg.status || msg.phase;
    state.round = msg.round;
    state.deadline = msg.deadline ?? null;
    state.forcedSubmit = !!msg.forcedSubmit;
    if (state.phase === "PHASE1") {
      state.currentQuestion = null;
      state.progress = { acted: [], total: msg.progress?.total ?? state.count };
      state.confirmed = [];
      if (msg.round > prevRound) state.replay = [];
    }
    if (state.phase === "PHASE2") state.currentQuestion = state.currentQuestion || null;
    if (state.phase === "PHASE3") state.replay = [];
    if (state.phase === "READING") state.deadline = msg.deadline;
    emit("phase", msg);
    emit("state", state);
    return;
  }

  if (type === "persona:assigned") {
    state.yourCard = msg.yourCard || null;
    state.cardNames = msg.cardNames || [];
    state.myRoomNo = msg.yourRoomNo ?? state.myRoomNo;
    state.roomNos = msg.roomNos || state.roomNos;
    state.deadline = msg.deadline ?? state.deadline;
    emit("assigned", msg);
    emit("state", state);
    return;
  }

  if (type === "card:progress") {
    state.cards = { submitted: msg.submitted, total: msg.total };
    emit("state", state);
    return;
  }

  if (type === "card:submitted") {
    state.cardSubmitted = true;
    state.yourWrittenCard = msg.card || null;
    emit("state", state);
    return;
  }

  if (type === "reading:progress") {
    state.readingProgress = { confirmed: msg.confirmed, total: msg.total };
    emit("state", state);
    return;
  }

  if (type === "room:aiAdded") {
    toast(`已请来 ${(msg.players || []).map((p) => p.nickname).join("、")}`);
    return;
  }

  if (type === "ai:thinking") {
    state.aiThinking[msg.playerId] = msg.kind;
    pushFeed({ kind: "ai", text: `${msg.nickname} ${
      { write_card: "正在写卡", phase1: "正在做决定", answer: "正在作答" }[msg.kind] || "正在思考"
    }…` });
    return;
  }

  if (type === "question:received") {
    state.currentQuestion = {
      questionId: msg.questionId,
      askerId: msg.askerId,
      askerNickname: msg.askerNickname,
      text: msg.text,
      deadline: msg.deadline,
      queuePosition: msg.queuePosition,
    };
    upsertThread(msg.questionId, {
      asker: msg.askerNickname,
      targetNo: state.myRoomNo,
      text: msg.text,
      status: "PENDING",
      toMe: true, // 这是「别人问我」，不是我在问
    });
    emit("state", state);
    return;
  }

  if (type === "answer:public") {
    upsertThread(msg.questionId, {
      answer: msg.timedOut ? null : msg.answer,
      masked: !!msg.masked,
      timedOut: !!msg.timedOut,
      answerNo: msg.targetNo ?? null,
      status: msg.status,
    });
    return;
  }

  if (type === "question:public") {
    upsertThread(msg.questionId, {
      asker: msg.askerNickname,
      targetNo: msg.targetNo ?? null,
      text: msg.text,
      status: msg.status,
      mine: false,
    });
    return;
  }

  if (type === "phase2:progress" || type === "phase3:progress") {
    state.progress = { ...state.progress, ...msg };
    emit("state", state);
    return;
  }

  if (type === "phase3:replay") {
    state.replay = msg.items || [];
    emit("state", state);
    return;
  }

  if (type === "phase2:nextQuestion") {
    state.currentQuestion = {
      questionId: msg.questionId,
      askerId: msg.askerId,
      askerNickname: msg.askerNickname,
      text: msg.text,
      deadline: msg.deadline,
    };
    emit("state", state);
    return;
  }

  if (type === "qa:privateNotice") {
    pushFeed({ kind: "locked", text: msg.text || "本轮有一条私密问答（仅当事人可见）", round: msg.round });
    return;
  }

  if (type === "board:draftSaved") {
    state.board = { ...(msg.board || {}) };
    emit("state", state);
    return;
  }

  if (type === "board:progress" || type === "submit:result") {
    if (type === "submit:result" && msg.correct === false) {
      state.lastSubmit = {
        round: msg.round,
        missing: msg.missing || [],
        wrong: msg.wrong || [],
        cooldown: msg.cooldown || 0,
      };
      const detail = [];
      if (msg.wrong?.length) detail.push(`猜错 ${msg.wrong.length} 格（${msg.wrong.map((n) => n + " 号").join("、")}）`);
      if (msg.missing?.length) detail.push(`还有 ${msg.missing.length} 格没猜（${msg.missing.map((n) => n + " 号").join("、")}）`);
      toast(`看板未通过：${detail.join("，") || "有格子不对"}`, "error");
    }
    emit("submit", msg);
    emit("state", state);
    return;
  }

  if (type === "cooldown:updated") {
    state.you = { ...state.you, cooldown: msg.cooldown };
    emit("state", state);
    return;
  }

  if (type === "round:ended") {
    // 保留历史（翻页要能往回看），只重置这一轮的"猜错/未猜"标记
    state.feed = (state.feed || []).slice(-200);
    state.feedViewRound = undefined;
    state.lastSubmit = null;
    emit("state", state);
    return;
  }

  if (type === "game:over") {
    state.over = msg;
    state.phase = "OVER";
    emit("over", msg);
    emit("state", state);
    return;
  }

  if (type === "reconnect:ok") {
    applySnapshot(msg.snapshot || {});
    toast("已回到座位");
    emit("state", state);
    return;
  }

  if (type === "reconnect:failed") {
    forgetToken();
    toast("座位已失效，请重新入场", "error");
    return;
  }

  emit(type, msg);
}

function applySnapshot(snap) {
  state.playerId = state.playerId || null;
  state.roomCode = snap.roomCode || state.roomCode;
  state.phase = snap.phase || state.phase;
  state.status = snap.status || state.status;
  state.gameMode = snap.gameMode || state.gameMode;
  state.round = snap.round ?? state.round;
  state.deadline = snap.deadline ?? null;
  state.players = snap.players || state.players;
  state.config = snap.config || state.config;
  state.myRoomNo = snap.yourRoomNo ?? state.myRoomNo;
  state.roomNos = snap.roomNos || state.roomNos;
  state.nicknames = snap.nicknames || state.nicknames;
  state.board = snap.board || {};
  state.replay = snap.replay || [];
  state.yourCard = snap.yourCard || null;
  state.cardNames = snap.cardNames || [];
  if (snap.cards) state.cards = snap.cards;
  if (snap.currentQuestion) state.currentQuestion = snap.currentQuestion;
}

export /** 问答线程：同一个 questionId 的问题与回答合并成一条，渲染时成对显示 */
function msgRound(questionId) {
  const found = (state.feed || []).find((x) => x && x.questionId === questionId && x.round);
  return found?.round || state.round || 1;
}

function upsertThread(questionId, patch) {
  if (!questionId) return;
  let item = (state.feed || []).find((x) => x && x.questionId === questionId);
  if (!item) {
    item = { kind: "thread", questionId, round: msgRound(questionId) };
    state.feed.push(item);
  }
  Object.assign(item, patch);
  emit("feed", state.feed);
}

function pushFeed(item) {
  state.feed.push(item);
  if (state.feed.length > 150) state.feed.shift();
  emit("feed", state.feed);
}

/* ------------------------------------------------------------------ */
/* 重连凭据（sessionStorage：每个标签页独立，互不抢占座位）             */
/* ------------------------------------------------------------------ */

function saveToken(roomCode, playerId, token) {
  try {
    store.setItem(
      TOKEN_KEY,
      JSON.stringify({ roomCode, playerId, token, at: Date.now() })
    );
  } catch {
    /* 隐私模式下写不进去，忽略 */
  }
}

function rememberToken() {
  if (state.you && state.you.reconnectToken) {
    saveToken(state.roomCode, state.you.id, state.you.reconnectToken);
  }
}

export function forgetToken() {
  try {
    store.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function savedToken() {
  try {
    const raw = store.getItem(TOKEN_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}


/** 本次页面加载是不是「刷新」？（新标签页/复制标签页算 navigate） */
function isReload() {
  try {
    const nav = performance.getEntriesByType(navigation)[0];
    if (nav && nav.type) return nav.type === reload;
    return performance.navigation && performance.navigation.type === 1;
  } catch {
    return false;
  }
}

function tryResume() {
  if (state.playerId) return; // 本条连接已经在房间里
  // 只有「刷新同一个标签页」才自动回座；
  // 新开/复制的标签页应该是一张新票，不能去抢别人的座位。
  if (!isReload()) return;
  const saved = savedToken();
  if (!saved || !saved.token) return;
  if (Date.now() - (saved.at || 0) > 1000 * 60 * 60 * 12) {
    forgetToken();
    return;
  }
  state.playerId = saved.playerId;
  state.roomCode = saved.roomCode;
  send("conn:reconnect", {
    roomCode: saved.roomCode,
    playerId: saved.playerId,
    token: saved.token,
  });
}

export function hardReset() {
  forgetToken();
  state.playerId = null;
  state.roomCode = null;
  state.phase = "LOBBY";
  state.over = null;
  state.feed = [];
  state.you = {};
}
