export function fuzzyFilter(items, query, getText) {
  if (!query) return items;
  const q = query.toLowerCase();
  return items
    .map((item) => {
      const text = getText(item).toLowerCase();
      const idx = text.indexOf(q);
      return { item, idx };
    })
    .filter((x) => x.idx !== -1)
    .sort((a, b) => a.idx - b.idx)
    .map((x) => x.item);
}

export function flattenFiles(node, out = []) {
  if (!node) return out;
  if (node.type === "file") {
    out.push(node.path);
  } else if (node.children) {
    node.children.forEach((child) => flattenFiles(child, out));
  }
  return out;
}
