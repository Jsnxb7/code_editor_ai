const ICONS = {
  bat: { glyph: "BAT", color: "#7a8094" },
  c: { glyph: "C", color: "#5b9df0" },
  cpp: { glyph: "C++", color: "#5b9df0" },
  cs: { glyph: "C#", color: "#8f7cff" },
  py: { glyph: "PY", color: "#3fa7ff" },
  html: { glyph: "<>", color: "#e8633f" },
  css: { glyph: "#", color: "#5b9df0" },
  go: { glyph: "GO", color: "#4dd9ec" },
  java: { glyph: "J", color: "#e8633f" },
  js: { glyph: "JS", color: "#f5c842" },
  jsx: { glyph: "JS", color: "#f5c842" },
  ts: { glyph: "TS", color: "#4a9cff" },
  tsx: { glyph: "TS", color: "#4a9cff" },
  json: { glyph: "{}", color: "#d9b35a" },
  md: { glyph: "MD", color: "#9ba3b8" },
  php: { glyph: "PHP", color: "#8f7cff" },
  ps1: { glyph: "PS", color: "#4a9cff" },
  rb: { glyph: "RB", color: "#f56060" },
  rs: { glyph: "RS", color: "#d9945a" },
  sh: { glyph: "SH", color: "#52d68a" },
  sql: { glyph: "SQL", color: "#4dd9ec" },
  svg: { glyph: "SVG", color: "#f5a623" },
  toml: { glyph: "T", color: "#d9945a" },
  txt: { glyph: "TXT", color: "#7a8094" },
  xml: { glyph: "<>", color: "#e8633f" },
  yml: { glyph: "Y", color: "#52d68a" },
  yaml: { glyph: "Y", color: "#52d68a" },
};

export function fileIcon(name = "") {
  const ext = name.split(".").pop().toLowerCase();
  return ICONS[ext] || { glyph: "TXT", color: "#5a6070" };
}
