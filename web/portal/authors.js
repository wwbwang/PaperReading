import { readingState, browserStorage, element, externalLink } from "/reading-state.mjs";
import katex from "/author-assets/katex.mjs";
import { abstractParts, normalizeTex } from "/author-assets/abstract-math.mjs";

const $ = selector => document.querySelector(selector);
let data, author, state, filtered = [], limit = 30;
const normalize = value => value.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
const date = value => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
function storageStatus() { $("#storage-status").textContent = state.available ? "" : "浏览器存储不可用，本次已读与关注更改仅在当前页面有效。"; }
function followButton() {
  const followed = state.follows(author.id);
  $("#follow-author").textContent = followed ? "已关注 ✓" : "+ 关注作者";
  $("#follow-author").classList.toggle("primary", !followed);
  $("#follow-author").setAttribute("aria-pressed", String(followed));
  $("#follow-author").setAttribute("aria-label", `${followed ? "取消关注" : "关注"}${author.name}`);
}
function setAuthor() {
  limit = 30;
  author = data.authors.find(item => item.id === $("#author-picker").value) || data.authors[0];
  const url = new URL(location.href);url.searchParams.set("author", author.id);history.replaceState(null, "", url);
  document.title = `${author.name} · 作者跟踪 · PaperReading`;
  $("#author-name").textContent = author.name;
  $("#author-name-en").textContent = author.name_en;
  $("#author-avatar").textContent = author.initials;
  $("#author-affiliation").textContent = `${author.affiliation} · ${author.department}`;
  $("#author-topics").replaceChildren(...author.topics.map(topic => element("span", topic)));
  $("#author-links").replaceChildren(externalLink("官方导师主页 ↗", author.profile_url), externalLink("团队主页 ↗", author.team_url), externalLink("团队论文目录 ↗", author.publications_url));
  $("#identity-note").textContent = `${author.identity_note} 身份核对日期：${author.identity_verified_at}。`;
  $("#coverage-summary").textContent = `${author.verifiedCount} 条已核实 · ${author.candidateCount} 条同名待核实 · 数据范围与规则`;
  const gaps = author.coverage.filter(item => item.papers > 0 && !item.publicAuthorPapers);
  const missing = author.coverage.filter(item => item.status === "unavailable");
  $("#coverage-gaps").textContent = `${gaps.length ? "当前有论文但无公开作者的快照：" + gaps.map(item => `${item.venue.toUpperCase()} ${item.year}`).join("、") + "。" : ""}另有 ${missing.length} 个来源/年份的记录尚未获取；跟踪结果不代表作者的全部成果。`;
  $("#index-updated").textContent = `本地索引更新：${date(data.updated_at)}（北京时间）；团队目录获取：${date(author.evidence_retrieved_at)}（北京时间）。`;
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
}
async function init() {
  const response = await fetch("/authors.json");if (!response.ok) throw new Error("Author index unavailable");
  data = await response.json();if (!data.authors.length) throw new Error("Watchlist empty");
  state = readingState(data.authors.map(item => item.id), browserStorage());
  $("#author-picker").replaceChildren(...data.authors.map(item => new Option(`${item.name} · ${item.name_en}`, item.id)));
  $("#author-picker").hidden = data.authors.length < 2;
  const requested = new URLSearchParams(location.search).get("author");
  $("#author-picker").value = data.authors.some(item => item.id === requested) ? requested : data.authors[0].id;
  $("#author-picker").addEventListener("change", setAuthor);
  $("#author-filters").addEventListener("submit", event => event.preventDefault());
  $("#author-filters").addEventListener("input", () => { limit = 30;render(); });
  $("#author-filters").addEventListener("change", () => { limit = 30;render(); });
  $("#follow-author").addEventListener("click", () => { state.follow(author.id);followButton();storageStatus(); });
  $("#mark-visible-read").addEventListener("click", () => { state.mark(author.id, filtered.map(paper => paper.key), true);storageStatus();render(); });
  $("#load-more").addEventListener("click", () => { limit += 30;render(); });
  setAuthor();$("#load-status").hidden = true;$("#author-content").hidden = false;
}
init().catch(() => { $("#load-status").replaceChildren(document.createTextNode("作者索引暂不可用。"));const retry = element("button", "重新加载");retry.type = "button";retry.addEventListener("click", () => location.reload());$("#load-status").append(retry); });
