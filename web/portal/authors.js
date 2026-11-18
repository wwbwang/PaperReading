import { readingState, browserStorage, element, externalLink } from "/reading-state.mjs";
import katex from "/author-assets/katex.mjs";
import { abstractParts, normalizeTex } from "/author-assets/abstract-math.mjs";

const $ = selector => document.querySelector(selector);
const authorButtons = new Map();
let data, author, state, filtered = [], limit = 30;
let drag = null, suppressClick = false;
const normalize = value => value.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
function storageStatus() { $("#storage-status").textContent = state.available ? "" : "浏览器存储不可用，本次已读与关注更改仅在当前页面有效。"; }
function followButton() {
  const followed = state.follows(author.id);
  $("#follow-author").textContent = followed ? "已关注 ✓" : "+ 关注作者";
  $("#follow-author").classList.toggle("primary", !followed);
  $("#follow-author").setAttribute("aria-pressed", String(followed));
  $("#follow-author").setAttribute("aria-label", `${followed ? "取消关注" : "关注"}${author.name}`);
}
function updateAuthorButton(item) {
  const { button, status } = authorButtons.get(item.id);
  if (item === author) button.setAttribute("aria-current", "true");
  else button.removeAttribute("aria-current");
  const unread = item.papers.filter(paper => paper.identity === "verified" && !state.isRead(item.id, paper.key)).length;
  status.textContent = state.follows(item.id) ? `${unread} 未读` : "未关注";
}
function applyAuthorOrder() {
  $("#author-list").append(...state.authorOrder.map(id => authorButtons.get(id).row));
}
function moveAuthor(id, position) {
  state.moveAuthor(id, position);
  applyAuthorOrder();
  authorButtons.get(id).button.focus({ preventScroll: true });
  storageStatus();
}
function buildAuthorList() {
  for (const item of data.authors) {
    const row = element("li");
    const button = element("button");
    const name = element("span", item.name, "directory-name");
    const status = element("span", undefined, "directory-status");
    button.type = "button";
    button.setAttribute("aria-keyshortcuts", "Alt+ArrowUp Alt+ArrowDown");
    button.append(name, status);
    button.addEventListener("click", event => {
      if ((!suppressClick || event.detail === 0) && item !== author) setAuthor(item);
    });
    button.addEventListener("keydown", event => {
      if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const order = state.authorOrder;
      const destination = order.indexOf(item.id) + (event.key === "ArrowUp" ? -1 : 1);
      if (destination >= 0 && destination < order.length) moveAuthor(item.id, destination);
    });
    button.addEventListener("pointerdown", event => {
      if (event.button !== 0 || drag) return;
      suppressClick = false;
      drag = { id: item.id, pointerId: event.pointerId, row, button, x: event.clientX, y: event.clientY };
    });
    row.append(button);
    authorButtons.set(item.id, { row, button, status });
    updateAuthorButton(item);
  }
  applyAuthorOrder();
}
function authorRowAt(event) {
  return document.elementFromPoint(event.clientX, event.clientY)?.closest("#author-list > li");
}
function endDrag(event) {
  if (!drag || (event.type !== "blur" && drag.pointerId !== event.pointerId)) return;
  const { id, row, button, active } = drag;
  drag = null;
  button.style.transform = "";
  row.classList.remove("dragging");
  $("#author-list .drop-target")?.classList.remove("drop-target");
  suppressClick = Boolean(active);
  const target = active && event.type === "pointerup" && authorRowAt(event);
  if (target && target !== row) moveAuthor(id, Array.from($("#author-list").children).indexOf(target));
}
function setAuthor(selected) {
  limit = 30;
  const previous = author;
  author = selected;
  $(".author-main").hidden = false;
  if (previous) updateAuthorButton(previous);
  const url = new URL(location.href);url.searchParams.set("author", author.id);history.replaceState(null, "", url);
  document.title = `${author.name} · 作者跟踪 · PaperReading`;
  $("#author-name").textContent = author.name;
  $("#author-name-en").textContent = author.name_en;
  $("#author-avatar").textContent = author.initials;
  $("#author-affiliation").textContent = [author.affiliation, author.department].filter(Boolean).join(" · ");
  $("#author-topics").replaceChildren(...author.topics.map(topic => element("span", topic)));
  const links = [["作者主页 ↗", author.profile_url], ["团队主页 ↗", author.team_url], ["论文目录 ↗", author.publications_url]];
  $("#author-links").replaceChildren(...links.filter(([, url]) => url).map(([label, url]) => externalLink(label, url)));
  const venues = [...new Map(author.papers.map(paper => [paper.venue, paper.venueLabel])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  $("#author-venue").replaceChildren(new Option("全部来源", "all"), ...venues.map(([value, label]) => new Option(label, value)));
  followButton();storageStatus();render();
}
function paperCard(paper) {
  const card = element("article", undefined, "paper-item");
  const body = element("div"), meta = element("div", undefined, "paper-meta");
  meta.append(element("span", `${paper.venueLabel} ${paper.year}`), element("span", paper.identity === "verified" ? "已核实" : "同名待核实", `identity-tag ${paper.identity}`), element("span", paper.status));
  if (paper.rating_count) meta.append(element("span", `均分 ${Number(paper.rating_mean).toFixed(2)} · ${paper.rating_count} 位评分`));
  const title = element("h3"), titleText = paper.paper_url ? externalLink("", paper.paper_url) : element("span");
  for (const part of abstractParts(paper.title)) {
    if (part.tex === undefined) { titleText.append(document.createTextNode(part.text));continue; }
    const math = element("span");
    try { math.innerHTML = katex.renderToString(normalizeTex(part.tex), { trust: false, throwOnError: true, strict: "ignore", maxExpand: 1000, maxSize: 20 }); }
    catch { math.textContent = part.source; }
    titleText.append(math);
  }
  if (paper.paper_url) titleText.append(document.createTextNode(" ↗"));
  title.append(titleText);
  const links = element("div", undefined, "paper-links");
  if (paper.paper_url) links.append(externalLink("论文来源 ↗", paper.paper_url));
  if (paper.pdf_url) links.append(externalLink("论文 PDF ↗", paper.pdf_url));
  if (paper.evidence_url) links.append(externalLink("身份核实依据 ↗", paper.evidence_url));
  const library = element("a", "该届论文库 →");library.href = `/${paper.venue}/${paper.year}/`;links.append(library);
  body.append(meta, title, element("p", paper.authors.join(" · "), "paper-authors"), links);
  const read = state.isRead(author.id, paper.key), button = element("button", read ? "已读 ✓" : "标为已读", "read-button");
  button.type = "button";button.setAttribute("aria-pressed", String(read));button.setAttribute("aria-label", `${read ? "标为未读" : "标为已读"}：${paper.title}`);
  button.addEventListener("click", () => { state.mark(author.id, [paper.key], !state.isRead(author.id, paper.key));storageStatus();render(); });
  card.append(body, button);return card;
}
function render() {
  const query = normalize($("#author-query").value), year = $("#author-year").value, venue = $("#author-venue").value, identity = $("#identity-filter").value;
  filtered = author.papers.filter(paper => (year === "all" || String(paper.year) === year) && (venue === "all" || paper.venue === venue)
    && (identity === "all" || paper.identity === identity) && normalize(paper.title).includes(query) && (!$("#unread-only").checked || !state.isRead(author.id, paper.key)));
  const unread = filtered.filter(paper => !state.isRead(author.id, paper.key)).length;
  $("#paper-count").textContent = `${filtered.length} 条收录记录 · ${unread} 条未读`;
  $("#author-papers").replaceChildren(...(filtered.length ? filtered.slice(0, limit).map(paperCard) : [element("p", "当前筛选下没有记录。可以调整年份、来源或身份核实条件。", "empty-state")]));
  $("#load-more").hidden = filtered.length <= limit;
  $("#mark-visible-read").disabled = !unread;
  updateAuthorButton(author);
}
async function init() {
  const response = await fetch("/authors.json");if (!response.ok) throw new Error("Author index unavailable");
  data = await response.json();if (!data.authors.length) throw new Error("Watchlist empty");
  state = readingState(data.authors.map(item => item.id), browserStorage());
  buildAuthorList();
  document.addEventListener("pointermove", event => {
    if (drag?.pointerId !== event.pointerId) return;
    const x = event.clientX - drag.x;
    const y = event.clientY - drag.y;
    if (!drag.active) {
      if (Math.hypot(x, y) < 6) return;
      drag.active = true;
      drag.row.classList.add("dragging");
    }
    drag.button.style.transform = `translate(${x}px, ${y}px)`;
    $("#author-list .drop-target")?.classList.remove("drop-target");
    const target = authorRowAt(event);
    if (target && target !== drag.row) target.classList.add("drop-target");
  });
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  window.addEventListener("blur", endDrag);
  const requested = new URLSearchParams(location.search).get("author");
  $("#author-filters").addEventListener("submit", event => event.preventDefault());
  $("#author-filters").addEventListener("input", () => { limit = 30;render(); });
  $("#author-filters").addEventListener("change", () => { limit = 30;render(); });
  $("#follow-author").addEventListener("click", () => { state.follow(author.id);followButton();storageStatus();updateAuthorButton(author); });
  $("#mark-visible-read").addEventListener("click", () => { state.mark(author.id, filtered.map(paper => paper.key), true);storageStatus();render(); });
  $("#load-more").addEventListener("click", () => { limit += 30;render(); });
  const selected = data.authors.find(item => item.id === requested);
  if (selected) setAuthor(selected);
  storageStatus();
  $("#load-status").hidden = true;$("#author-content").hidden = false;
}
init().catch(() => { $("#load-status").replaceChildren(document.createTextNode("作者索引暂不可用。"));const retry = element("button", "重新加载");retry.type = "button";retry.addEventListener("click", () => location.reload());$("#load-status").append(retry); });
