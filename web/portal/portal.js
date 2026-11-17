import { readingState, browserStorage, element } from "/reading-state.mjs";

const cards = [...document.querySelectorAll("article.conference")];
const search = document.querySelector("#venue-search");
const year = document.querySelector("#library-year");
let kind = "all";
const normalize = value => value.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
function filter() {
  let count = 0;
  const query = normalize(search.value);
  for (const card of cards) {
    card.hidden = (kind !== "all" && card.dataset.kind !== kind) || !normalize(card.querySelector(".conference-header").textContent + card.querySelector(".venue-name").textContent).includes(query);
    if (!card.hidden) count++;
    for (const link of card.querySelectorAll(".year-card")) link.hidden = year.value !== "all" && link.dataset.year !== year.value;
  }
  document.querySelector("#venue-count").textContent = `${count} 个来源`;
  document.querySelector("#no-venues").hidden = count !== 0;
  document.querySelector("#reset-library").hidden = !search.value && kind === "all" && year.value === "all";
}
for (const button of document.querySelectorAll(".category-tabs button")) button.addEventListener("click", () => {
  kind = button.dataset.kind;
  for (const tab of document.querySelectorAll(".category-tabs button")) tab.setAttribute("aria-pressed", String(tab === button));
  filter();
});
search.addEventListener("input", filter);
year.addEventListener("change", filter);
document.querySelector("#reset-library").addEventListener("click", () => {
  search.value = "";
  year.value = "all";
  document.querySelector('.category-tabs button[data-kind="all"]').click();
  search.focus();
});
filter();

async function loadAuthors() {
  const response = await fetch("/authors.json");
  if (!response.ok) throw new Error("Author index unavailable");
  const data = await response.json();
  const state = readingState(data.authors.map(author => author.id), browserStorage());
  const container = document.querySelector("#tracked-authors");
  container.replaceChildren();
  for (const author of data.authors.filter(author => state.follows(author.id))) {
    const link = element("a", undefined, "author-preview");
    link.href = `/authors/?author=${encodeURIComponent(author.id)}`;
    link.append(element("span", author.initials, "avatar"));
    const info = element("div");
    const heading = element("div");
    heading.append(element("strong", author.name), element("span", author.name_en, "name-en"));
    info.append(heading, element("p", author.affiliation));
    link.append(info, element("span", "→", "author-arrow"));
    const counts = element("div", undefined, "preview-count");
    const unread = author.papers.filter(paper => paper.identity === "verified" && !state.isRead(author.id, paper.key)).length;
    for (const [count, label] of [[author.verifiedCount, "已核实记录"], [unread, "未读"]]) {
      const value = element("span");value.append(element("strong", count), document.createTextNode(label));counts.append(value);
    }
    container.append(link, counts);
  }
  if (!container.childElementCount) container.append(element("p", "暂未关注作者，可进入作者跟踪页恢复关注。", "muted"));
}
loadAuthors().catch(() => { document.querySelector("#tracked-authors").replaceChildren(element("p", "作者索引暂不可用，请刷新重试。", "muted")); });
window.addEventListener("pageshow", event => { if (event.persisted) loadAuthors().catch(() => {}); });
