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
