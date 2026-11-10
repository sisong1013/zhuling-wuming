/* card.js —— 写卡：字数统计、交卡、队长开始分配 */

import { esc, toast } from "./ui.js";

const NAME_MAX = 20;
const CONTENT_MAX = 300;

export function renderCard(root, state, { send }) {
  if (!root) return;
  const submitted = state.cards?.submitted ?? 0;
  const total = state.cards?.total ?? state.count;
  const isCaptain = !!(state.you && state.you.isCaptain);
  const ready = total > 0 && submitted >= total;
  const mine = state.yourWrittenCard || {};

  root.innerHTML = `
    <div class="card card--playbill">
      <div class="card__rubric"><span>写卡</span></div>
      <h2 class="card-title">写一张人设卡</h2>
      <p class="hint">这张卡会被<b>错位</b>发到别人手里，你还得靠问答猜出别人拿的是哪张。写的时候别写下自己的名字。</p>

      <label class="field">
        <span>卡名（1–${NAME_MAX} 字，全场唯一）</span>
        <input id="card-name" maxlength="${NAME_MAX}" autocomplete="off"
          placeholder="比如：雾港的更夫" value="${esc(mine.name || "")}"
          ${state.cardSubmitted ? "disabled" : ""} />
        <em class="counter" id="name-count">0/${NAME_MAX}</em>
      </label>

      <label class="field">
        <span>卡面（≤${CONTENT_MAX} 字）</span>
        <textarea id="card-content" rows="5" maxlength="${CONTENT_MAX}"
          placeholder="这个角色说话什么味道？怕什么？有什么怪癖？"
          ${state.cardSubmitted ? "disabled" : ""}>${esc(mine.content || "")}</textarea>
        <em class="counter" id="content-count">0/${CONTENT_MAX}</em>
      </label>

      <div class="row-actions">
        <button class="btn primary" id="btn-submit-card" ${state.cardSubmitted ? "disabled" : ""}>
          ${state.cardSubmitted ? "已交卡" : "交卡"}
        </button>
        ${
          isCaptain
            ? `<button class="btn" id="btn-start-assign" ${ready ? "" : "disabled"}>开始错位分配</button>`
            : ""
        }
      </div>
      <p class="hint" id="card-hint">${
        ready
          ? isCaptain
            ? `全员已交齐（${submitted}/${total}），可以分配了`
            : `全员已交齐（${submitted}/${total}），等团长分配`
          : `已交 ${submitted}/${total} 张卡`
      }</p>
    </div>`;

  const nameEl = root.querySelector("#card-name");
  const contentEl = root.querySelector("#card-content");
  const nameCount = root.querySelector("#name-count");
  const contentCount = root.querySelector("#content-count");

  const sync = () => {
    if (nameCount) nameCount.textContent = `${nameEl.value.trim().length}/${NAME_MAX}`;
    if (contentCount) contentCount.textContent = `${contentEl.value.length}/${CONTENT_MAX}`;
  };
  nameEl?.addEventListener("input", sync);
  contentEl?.addEventListener("input", sync);
  sync();

  root.querySelector("#btn-submit-card")?.addEventListener("click", () => {
    const name = nameEl.value.trim();
    const content = contentEl.value.trim();
    if (!name) return toast("卡名不能为空", "error");
    if (name.length > NAME_MAX) return toast(`卡名最多 ${NAME_MAX} 字`, "error");
    if (!content) return toast("卡面不能为空", "error");
    if (content.length > CONTENT_MAX) return toast(`卡面最多 ${CONTENT_MAX} 字`, "error");
    send("card:submit", { name, content });
  });

  root.querySelector("#btn-start-assign")?.addEventListener("click", () =>
    send("captain:startAssign", {})
  );
}
