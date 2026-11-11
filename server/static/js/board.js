/* board.js —— 观众板抽屉：编号 → 真人 / 卡名，草稿与呈交 */

import { esc, toast } from "./ui.js";

const PERSONA = "PERSONA";

export function renderBoard(root, state, { send }) {
  if (!root) return;

  const numbers = state.roomNos.length
    ? state.roomNos
    : Object.keys(state.board || {}).map(Number).sort((a, b) => a - b);
  const persona = state.gameMode === PERSONA;
  const choices = persona && state.cardNames.length ? state.cardNames : state.nicknames;
  const ownNo = state.myRoomNo;

  const cells = numbers
    .map((no) => {
      const own = no === ownNo;
      const mine =
        (persona ? (state.yourCard && state.yourCard.name) : state.you.nickname) || "";
      const value = own ? mine : state.board[String(no)] || "";
      const options = [`<option value="">待猜</option>`]
        .concat(choices.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`))
        .join("");
      const last = state.lastSubmit || {};
      const reviewing = last.round === state.round && ((last.wrong || []).length || (last.missing || []).length);
      const marked = reviewing
        ? (last.wrong || []).includes(no)
          ? "is-wrong"
          : (last.missing || []).includes(no)
          ? "is-missing"
          : ""
        : "";
      const badge =
        marked === "is-wrong"
          ? '<span class="mark wrong">猜错</span>'
          : marked === "is-missing"
          ? '<span class="mark missing">未猜</span>'
          : own
          ? '<span class="lock">本人</span>'
          : "";
      return `
        <div class="board-cell ${own ? "is-locked" : ""} ${marked}">
          <span class="no">${no} 号${badge}</span>
          <select data-no="${no}" ${own ? "disabled" : ""} aria-label="编号 ${no} 对应谁">
            ${own ? `<option value="${esc(mine)}" selected>${esc(mine)}</option>` : options}
          </select>
        </div>`;
    })
    .join("");

  const cooldown = state.you.cooldown || 0;
  const canSubmit =
    state.phase === "PHASE1" && !state.acted && (cooldown === 0 || state.forcedSubmit);

  root.innerHTML = `
    <div class="drawer__head">
      <h2 class="card-title">${persona ? "编号 → 卡名" : "编号 → 真人"}</h2>
      <button class="btn ghost small" data-close aria-label="收起看板">收起</button>
    </div>
    <div class="board">${cells}</div>
    <div class="row-actions">
      <button class="btn" data-draft ${state.phase === "PHASE1" ? "" : "disabled"}>记入草稿</button>
      <button class="btn primary" data-submit ${canSubmit ? "" : "disabled"}>呈上看板</button>
    </div>
    <p class="board-progress" data-progress></p>
    <p class="hint">${
      cooldown > 0
        ? `冷却中（剩 ${cooldown} 轮），本轮只能提问或略过`
        : state.acted
        ? "本幕已行动，等其他人…"
        : persona
        ? "自己那格是白送的（你当然知道自己的卡名）"
        : "自己那格是白送的（你当然知道自己的编号）"
    }</p>`;

  const refreshProgress = () => {
    const selects = [...root.querySelectorAll("select[data-no]")].filter((x) => !x.disabled);
    const filled = selects.filter((x) => x.value).length;
    const box = root.querySelector("[data-progress]");
    if (box) {
      box.textContent = filled
        ? `已选 ${filled}/${selects.length} 格 · 可以呈上了`
        : `还没选任何一格（点下拉选人/选卡）`;
    }
  };

  for (const sel of root.querySelectorAll("select[data-no]")) {
    sel.addEventListener("change", () => {
      state.board[String(sel.dataset.no)] = sel.value;
      sel.classList.toggle("is-empty", !sel.value);
      sel.closest(".board-cell")?.classList.toggle("is-picked", !!sel.value);
      refreshProgress();
    });
    sel.classList.toggle("is-empty", !sel.value && !sel.disabled);
    const cell = sel.closest(".board-cell");
    if (cell) cell.classList.toggle("is-picked", !!sel.value && !sel.disabled);
  }
  refreshProgress();

  root.querySelector("[data-close]")?.addEventListener("click", () => toggleBoard(false));
  root.querySelector("[data-draft]")?.addEventListener("click", () => {
    const board = collect(root);
    send("board:saveDraft", { board });
    toast("草稿已备好");
  });
  root.querySelector("[data-submit]")?.addEventListener("click", () => {
    const board = collect(root);
    if (!Object.keys(board).length) return toast("看板还空着：先在上面挑几格", "error");
    send("phase1:submit", { board });
  });
}

function collect(root) {
  const out = {};
  for (const sel of root.querySelectorAll("select[data-no]")) {
    if (sel.disabled) continue;
    if (sel.value) out[sel.dataset.no] = sel.value;
  }
  return out;
}

let boardState = null;
let boardCtx = null;

/** app.js 每次渲染时把最新 state / ctx 交给抽屉，保证「一打开就有内容」 */
export function bindBoardContext(state, ctx) {
  boardState = state;
  boardCtx = ctx;
}

export function toggleBoard(force) {
  const drawer = document.getElementById("board");
  if (!drawer) return false;
  const next = force === undefined ? drawer.hidden : !!force;
  drawer.hidden = !next;
  document.body.classList.toggle("drawer-open", next);
  const btn = document.getElementById("btn-open-board");
  if (btn) btn.setAttribute("aria-expanded", String(!!next));
  if (next && boardState) renderBoard(drawer, boardState, boardCtx);
  return !!next;
}

export function isBoardOpen() {
  const drawer = document.getElementById("board");
  return !!drawer && !drawer.hidden;
}
