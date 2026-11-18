// Personal state is browser-local; the paper evidence stays in the repository.
export function readingState(authorIds, storage) {
  let saved = {}, available = true;
  try { saved = JSON.parse(storage.getItem("paperreading.authors.v1") || "{}"); }
  catch { available = false; }
  // Before the watchlist expanded, Chao Dong was the only default author.
  const savedFollows = Array.isArray(saved?.followed) ? new Set(saved.followed) : null;
  const previousAuthors = new Set(Array.isArray(saved?.knownAuthors)
    ? saved.knownAuthors : ["chao-dong-siat", ...(savedFollows || [])]);
  const followed = new Set(authorIds.filter(id => !savedFollows || savedFollows.has(id) || !previousAuthors.has(id)));
  const read = new Set(Array.isArray(saved?.read) ? saved.read.filter(key => typeof key === "string") : []);
  const savedOrder = Array.isArray(saved?.authorOrder) ? saved.authorOrder.filter(id => authorIds.includes(id)) : [];
  const order = [...new Set([...savedOrder, ...authorIds])];
  function save() {
    try { storage.setItem("paperreading.authors.v1", JSON.stringify({ knownAuthors: authorIds, followed: [...followed], read: [...read], authorOrder: order })); }
    catch { available = false; }
    return available;
  }
  return {
    follows: id => followed.has(id),
    isRead: (id, key) => read.has(`${id}:${key}`),
    get authorOrder() { return [...order]; },
    moveAuthor(id, position) {
      const index = order.indexOf(id);
      if (index < 0 || index === position || !Number.isInteger(position) || position < 0 || position >= order.length) return;
      order.splice(index, 1);
      order.splice(position, 0, id);
      return save();
    },
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
