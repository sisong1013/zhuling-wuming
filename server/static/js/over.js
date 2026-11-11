/* over.js —— 谢幕：真实映射 + 名场面时间线 + 再来一出 */

import { esc, toast } from "./ui.js";

const TAG_CLASS = {
  opening: "tag-open",
  timeout: "tag-timeout",
  sharp: "tag-sharp",
  self_reveal: "tag-lie",
  longest: "tag-quote",
};

export function renderOver(root, state, { send, reset }) {
  if (!root) return;
  const over = state.over || {};
  const persona = (over.gameMode || state.gameMode) === "PERSONA";
  const win = state.players.find((p) => p.id === over.winnerId);
  const stats = over.stats || {};

  const mapping = persona
    ? (over.reveal || [])
        .map(
          (item) => `
        <li class="map-row">
          <span class="map-no">#${item.roomNo}</span>
          <span class="map-who">${esc(item.cardName || "?")}</span>
          <span class="map-note">${esc(item.authorNickname || "?")} 写</span>
          ${item.cardContent ? `<p class="map-content">${esc(item.cardContent)}</p>` : ""}
        </li>`
        )
        .join("")
    : Object.entries(over.fullBoard || {})
        .sort((a, b) => Number(a[0]) - Number(b[0]))
        .map(([no, who]) => {
          // 服务端下发的是 { 编号: {nickname, playerId} }，也兼容纯字符串
          const nick = typeof who === "string" ? who : (who && who.nickname) || "?";
          return `
        <li class="map-row">
          <span class="map-no">#${no}</span>
          <span class="map-who">${esc(nick)}</span>
        </li>`;
        })
        .join("");

  const timeline = (over.timeline || [])
    .map((item) => {
      const tags = (item.highlights || [])
        .map(
          (tag) =>
            `<span class="hl ${TAG_CLASS[tag] || ""}">${esc(
              (item.highlightLabels || [])[(item.highlights || []).indexOf(tag)] || tag
            )}</span>`
        )
        .join("");
      return `
      <li class="tl-item ${item.highlights?.length ? "has-hl" : ""} ${item.timedOut ? "is-timeout" : ""}">
        <span class="tl-round">R${item.round}</span>
        <div class="tl-body">
          <p class="tl-who">
            <b>${esc(item.askerNickname)}</b>
            <span class="tl-arrow">→</span>
            <b>#${item.targetNo ?? "?"}</b>
            ${tags}
          </p>
          <p class="tl-q">${esc(item.question)}</p>
          <p class="tl-a ${item.timedOut ? "is-timeout" : ""} ${item.masked ? "is-masked" : ""}">${
            item.timedOut
              ? "（超时未答）"
              : item.masked
              ? "🔒 已作答（内容仅当事人可见）"
              : esc(item.answer || "")
          }</p>
        </div>
      </li>`;
    })
    .join("");

  root.innerHTML = `
    <div class="card card--playbill over-card">
      <div class="card__rubric"><span>谢幕</span></div>
      <h2 class="card-title" id="overlay-title">
        ${win ? `${esc(win.nickname)} 揭开了整座剧团` : "这一场没有赢家"}
      </h2>
      <p class="hint">
        ${persona ? "人设卡模式" : "猜真人模式"} ·
        ${stats.rounds ?? state.round} 轮 ·
        ${stats.questions ?? 0} 次问答（超时 ${stats.timedOut ?? 0}）·
        高光 ${stats.highlights ?? 0} 处
      </p>

      <h3 class="sub-title">真正的对应关系</h3>
      <ul class="mapping" id="overlay-body">${mapping || '<li class="map-row">（无数据）</li>'}</ul>

      <h3 class="sub-title">名场面时间线</h3>
      <ul class="timeline" id="timeline">${timeline || '<li class="tl-item">这一场没有留下问句。</li>'}</ul>

      <div class="row-actions">
        <button class="btn primary" id="btn-again">再来一出</button>
        <button class="btn" id="btn-review-close">留在复盘</button>
      </div>
    </div>`;

  root.querySelector("#btn-again")?.addEventListener("click", () => {
    if (reset) reset();
    toast("回到入口，再来一出");
  });
  root.querySelector("#btn-review-close")?.addEventListener("click", () => {
    toast("复盘会一直留着");
  });
}
