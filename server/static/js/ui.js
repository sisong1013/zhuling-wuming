/* ui.js —— 纯工具：查询、转义、DOM 拼装、Toast、格式化 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

/** 极简模板：html`<b>${x}</b>`，插值一律转义 */
export function html(strings, ...values) {
  return strings.reduce((out, chunk, i) => {
    const v = values[i - 1];
    const safe =
      v && typeof v === "object" && v.__raw !== undefined ? v.__raw : esc(v);
    return out + safe + chunk;
  });
}

/** 明确标记「不要转义」的片段 */
export const raw = (s) => ({ __raw: String(s) });

export function setHTML(node, markup) {
  if (!node) return;
  node.innerHTML = markup;
}

export function show(node, visible = true) {
  if (node) node.hidden = !visible;
}

export function toast(text, kind = "") {
  const wrap = $("#toasts");
  if (!wrap) return;
  const el = document.createElement("div");
  el.className = `toast ${kind}`.trim();
  el.innerHTML = `<span>✦</span>${esc(text)}<span>✦</span>`;
  wrap.appendChild(el);
  setTimeout(() => {
    el.classList.add("is-out");
    setTimeout(() => el.remove(), 280);
  }, 1800);
}

export function fmtSeconds(deadline) {
  if (!deadline) return "—";
  const left = Math.max(0, deadline - Date.now() / 1000);
  return `${left.toFixed(0)}s`;
}

export function nickOf(state, playerId) {
  const p = (state.players || []).find((x) => x.id === playerId);
  return p ? p.nickname : "?";
}

export function isMe(state, playerId) {
  return state.you && state.you.id === playerId;
}
