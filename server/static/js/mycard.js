/* mycard.js —— 「我的人设卡」抽屉：随时回顾自己拿到的那张卡 */

import { esc } from "./ui.js";

let cardState = null;

export function syncMyCardButton(state) {
  cardState = state;
  const btn = document.getElementById("btn-my-card");
  if (!btn) return;
  const has = state.gameMode === "PERSONA" && state.yourCard;
  btn.hidden = !has;
  if (!has) {
    const drawer = document.getElementById("my-card");
    if (drawer) drawer.hidden = true;
    document.body.classList.remove("card-open");
  }
}

export function toggleMyCard(force) {
  const drawer = document.getElementById("my-card");
  if (!drawer) return false;
  const next = force === undefined ? drawer.hidden : !!force;
  drawer.hidden = !next;
  document.body.classList.toggle("card-open", next);
  const btn = document.getElementById("btn-my-card");
  if (btn) btn.setAttribute("aria-expanded", String(next));
  if (next && cardState) renderMyCard(drawer, cardState);
  return next;
}

export function renderMyCard(root, state) {
  if (!root || !state.yourCard) return;
  const card = state.yourCard;
  const mine = state.myRoomNo;
  root.innerHTML = `
    <div class="drawer__head">
      <h2 class="card-title">我拿到的人设卡</h2>
      <button class="btn ghost small" data-close aria-label="收起人设卡">收起</button>
    </div>
    <div class="mycard">
      <p class="mycard__no">${mine != null ? `你是 ${mine} 号` : ""}</p>
      <h3 class="mycard__name">${esc(card.name || "?")}</h3>
      <p class="mycard__content">${esc(card.content || "")}</p>
      <p class="hint">按这张卡的腔调说话——它可以撒谎。别报自己的编号，也别直说卡名。</p>
    </div>`;

  root.querySelector("[data-close]")?.addEventListener("click", () => toggleMyCard(false));
}
