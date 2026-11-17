// Personal state is browser-local; the paper evidence stays in the repository.
export function readingState(authorIds, storage) {
  let saved = {}, available = true;
  try { saved = JSON.parse(storage.getItem("paperreading.authors.v1") || "{}"); }
  catch { available = false; }
  const followed = new Set(Array.isArray(saved?.followed) ? saved.followed.filter(id => authorIds.includes(id)) : authorIds);
  const read = new Set(Array.isArray(saved?.read) ? saved.read.filter(key => typeof key === "string") : []);
  function save() {
    try { storage.setItem("paperreading.authors.v1", JSON.stringify({ followed: [...followed], read: [...read] })); }
    catch { available = false; }
    return available;
  }
  return {
    follows: id => followed.has(id),
    isRead: (id, key) => read.has(`${id}:${key}`),
    follow(id) { if (!authorIds.includes(id)) return; followed.has(id) ? followed.delete(id) : followed.add(id); return save(); },
    mark(id, keys, value) { for (const key of keys) value ? read.add(`${id}:${key}`) : read.delete(`${id}:${key}`); return save(); },
    get available() { return available; },
  };
}

export function browserStorage() {
  try { return window.localStorage; } catch { return { getItem() { throw new Error("Storage unavailable"); }, setItem() { throw new Error("Storage unavailable"); } }; }
}

export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function externalLink(label, url) {
  const link = element("a", label);
  link.href = /^https?:\/\//i.test(url) ? url : "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}
