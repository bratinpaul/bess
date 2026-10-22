// Render the BESS ERD as one HTML document (one page per schema + overview + indexes) for Chrome to print to PDF.
// Layout: ELK layered (elkjs). Usage: node erd.mjs <model.json> <out.html>
import fs from "node:fs";
import ELK from "elkjs/lib/elk.bundled.js";

const [, , modelPath, outPath] = process.argv;
const model = JSON.parse(fs.readFileSync(modelPath, "utf8"));
const elk = new ELK();

const COLORS = {
  battery_master: "#1f6f5c", battery_users: "#6d28d9", battery_raw: "#9a5b13",
  battery_telemetry: "#0b6aa2", battery_ml: "#a3245e", battery_itops: "#3f4b5b",
};
const BLURB = {
  battery_master: "Master and reference data: tenants, sites, battery systems and their assets, catalogues, market and dispatch data",
  battery_users: "Login, roles, permissions, refresh tokens, access requests and the auth audit trail",
  battery_raw: "Staging tables and batch logs for the loaders",
  battery_telemetry: "Time-series telemetry (TimescaleDB hypertables), alarms, dispatch events and their rollups",
  battery_ml: "ML runs, scores, predictions, KPIs and optimiser results",
  battery_itops: "Activity log written by the observability framework",
};
// layout direction per schema: DOWN spreads tables with many children (site, battery_system) into wide rows
const DIRECTION = JSON.parse(process.env.ERD_DIRECTION || "{}");
const FONT = 11, ROW = 17, HEAD = 26, PADX = 8, CHAR = 6.15, MAX_TYPE = 26;

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const short = (t) => t.replace("timestamp with time zone", "timestamptz").replace("timestamp without time zone", "timestamp")
  .replace("character varying", "varchar").replace("double precision", "float8").replace(/^integer$/, "int");
const typeText = (t) => { const s = short(t).replace(/battery_[a-z]+\./g, ""); return s.length > MAX_TYPE ? s.slice(0, MAX_TYPE - 1) + "…" : s; };

const rels = model.relations;
const byKey = new Map(rels.map((r) => [`${r.schema}.${r.name}`, r]));
const tablesOf = (s) => rels.filter((r) => r.schema === s && r.kind === "table");
const viewsOf = (s) => rels.filter((r) => r.schema === s && r.kind === "view");

function size(r) {
  const nameW = (r.name.length + (r.hypertable ? 12 : 0)) * (CHAR + 0.6) + 2 * PADX;
  let colW = 0;
  for (const c of r.columns) colW = Math.max(colW, 24 + c.name.length * CHAR + 16 + typeText(c.type).length * CHAR + 22);
  return { width: Math.ceil(Math.max(nameW, colW, 150)), height: HEAD + r.columns.length * ROW + 6 };
}

// ---------------------------------------------------------------- one schema diagram
async function layoutSchema(schema) {
  const tables = tablesOf(schema);
  const own = new Set(tables.map((t) => `${t.schema}.${t.name}`));
  const fks = model.foreign_keys.filter((f) => own.has(f.from));
  const ghosts = [...new Set(fks.filter((f) => !own.has(f.to)).map((f) => f.to))];
  const children = [
    ...tables.map((t) => ({ id: `${t.schema}.${t.name}`, ...size(t) })),
    ...ghosts.map((g) => ({ id: g, width: Math.max(150, g.length * CHAR + 20), height: 40 })),
  ];
  // edges point parent -> child so referenced (parent) tables sit to the left
  const edges = fks.map((f, i) => ({ id: `e${i}`, sources: [f.to], targets: [f.from] }));
  const graph = {
    id: schema,
    layoutOptions: {
      "elk.algorithm": "layered", "elk.direction": DIRECTION[schema] || "DOWN", "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": "90", "elk.spacing.nodeNode": "28",
      "elk.layered.spacing.edgeNodeBetweenLayers": "22", "elk.spacing.edgeEdge": "8",
      "elk.separateConnectedComponents": "true", "elk.spacing.componentComponent": "60",
      "elk.aspectRatio": "1.5", "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children, edges,
  };
  const res = await elk.layout(graph);
  return { res, tables, ghosts, fks };
}

function tableSvg(r, n, color) {
  const out = [];
  out.push(`<g transform="translate(${n.x},${n.y})">`);
  out.push(`<rect width="${n.width}" height="${n.height}" rx="5" fill="#fff" stroke="${color}" stroke-width="1.3"/>`);
  out.push(`<path d="M0,5 a5,5 0 0 1 5,-5 h${n.width - 10} a5,5 0 0 1 5,5 v${HEAD - 5} h-${n.width} z" fill="${color}"/>`);
  out.push(`<text x="${PADX}" y="17" class="th">${esc(r.name)}</text>`);
  if (r.hypertable) {
    const bx = n.width - 72;
    out.push(`<rect x="${bx}" y="6" width="64" height="14" rx="7" fill="#63F8BA"/><text x="${bx + 32}" y="16.5" class="badge">hypertable</text>`);
  }
  r.columns.forEach((c, i) => {
    const y = HEAD + i * ROW + 13;
    if (i % 2) out.push(`<rect x="1" y="${HEAD + i * ROW + 1}" width="${n.width - 2}" height="${ROW}" fill="#f5f7f8"/>`);
    const key = c.pk && c.fk ? "PF" : c.pk ? "PK" : c.fk ? "FK" : c.unique ? "UQ" : "";
    if (key) {
      const fill = c.pk ? "#f4c542" : c.fk ? "#9cc3f0" : "#d9dde3";
      out.push(`<rect x="5" y="${y - 10}" width="17" height="12" rx="2" fill="${fill}"/><text x="13.5" y="${y - 1}" class="key">${key}</text>`);
    }
    const ref = c.refs && c.refs.some((x) => !x.startsWith(r.schema + ".")) ? ` title="→ ${esc(c.refs.join(", "))}"` : "";
    out.push(`<text x="27" y="${y}" class="${c.pk ? "cpk" : "c"}"${ref}>${esc(c.name)}${c.not_null && !c.pk ? "" : ""}</text>`);
    out.push(`<text x="${n.width - 18}" y="${y}" class="t" text-anchor="end">${esc(typeText(c.type))}</text>`);
    if (c.not_null) out.push(`<text x="${n.width - 6}" y="${y}" class="nn" text-anchor="end">●</text>`);
  });
  out.push(`</g>`);
  return out.join("");
}

function ghostSvg(id, n) {
  const [s, t] = id.split(".");
  const color = COLORS[s] || "#888";
  return `<g transform="translate(${n.x},${n.y})"><rect width="${n.width}" height="${n.height}" rx="5" fill="#fafafa" stroke="${color}" stroke-dasharray="5 3"/>`
    + `<rect width="6" height="${n.height}" fill="${color}"/>`
    + `<text x="12" y="16" class="gs">${esc(s)}</text><text x="12" y="31" class="gt">${esc(t)}</text></g>`;
}

function edgeSvg(e) {
  const out = [];
  for (const sec of e.sections || []) {
    const pts = [sec.startPoint, ...(sec.bendPoints || []), sec.endPoint];
    out.push(`<polyline points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}" class="edge"/>`);
    const a = pts[0], b = pts[1], z = pts[pts.length - 1], y = pts[pts.length - 2];
    // parent end: "one" bar across the line; child end: crow's foot - for horizontal or vertical end segments
    const ux = Math.sign(b.x - a.x), uy = Math.sign(b.y - a.y);
    const bx = a.x + 6 * ux, by = a.y + 6 * uy;
    out.push(`<line x1="${bx - 5 * Math.abs(uy)}" y1="${by - 5 * Math.abs(ux)}" x2="${bx + 5 * Math.abs(uy)}" y2="${by + 5 * Math.abs(ux)}" class="edge"/>`);
    const vx = Math.sign(z.x - y.x), vy = Math.sign(z.y - y.y);
    const fx = z.x - 9 * vx, fy = z.y - 9 * vy, px = 5 * Math.abs(vy), py = 5 * Math.abs(vx);
    out.push(`<path d="M${fx},${fy} L${z.x - px},${z.y - py} M${fx},${fy} L${z.x},${z.y} M${fx},${fy} L${z.x + px},${z.y + py}" class="edge"/>`);
  }
  return out.join("");
}

async function schemaPage(schema, index) {
  const { res, tables, ghosts, fks } = await layoutSchema(schema);
  const color = COLORS[schema];
  const W = Math.ceil(res.width) + 80, H = Math.ceil(res.height) + 150;
  const nodes = new Map(res.children.map((n) => [n.id, n]));
  const body = [];
  for (const e of res.edges) body.push(edgeSvg(e));
  for (const t of tables) body.push(tableSvg(t, nodes.get(`${t.schema}.${t.name}`), color));
  for (const g of ghosts) body.push(ghostSvg(g, nodes.get(g)));
  const views = viewsOf(schema).length, hyper = tables.filter((t) => t.hypertable).length;
  const pw = Math.max(W, 1100);
  return {
    css: `@page p${index} { size: ${pw}px ${H}px; margin: 0 }`,
    html: `<section class="page" style="page:p${index};width:${pw}px;height:${H}px">
      <header style="border-color:${color}"><h1 style="color:${color}">${esc(schema)}</h1>
      <p>${esc(BLURB[schema] || "")}</p>
      <p class="stats">${tables.length} tables · ${hyper} hypertables · ${fks.length} foreign keys · ${views} views (see index)
       · dashed boxes are tables in other schemas</p></header>
      <svg width="${W}" height="${H - 110}" viewBox="-40 -10 ${W} ${H - 110}">${body.join("")}</svg></section>`,
  };
}

// ---------------------------------------------------------------- overview (schemas + cross-schema FKs)
async function overviewPage() {
  const counts = {};
  for (const f of model.foreign_keys) {
    const a = f.from.split(".")[0], b = f.to.split(".")[0];
    if (a !== b) counts[`${a}|${b}`] = (counts[`${a}|${b}`] || 0) + 1;
  }
  const children = model.schemas.map((s) => ({ id: s, width: 300, height: 120 }));
  const edges = Object.entries(counts).map(([k, n], i) => {
    const [a, b] = k.split("|");
    const text = `${n} FK${n > 1 ? "s" : ""}`;
    return { id: `o${i}`, sources: [b], targets: [a], labels: [{ text, width: text.length * 7 + 8, height: 16 }] };
  });
  const res = await elk.layout({
    id: "root", children, edges,
    layoutOptions: { "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": "140", "elk.spacing.nodeNode": "50",
      "elk.edgeLabels.inline": "false", "elk.spacing.componentComponent": "70" },
  });
  const body = [];
  for (const e of res.edges) {
    body.push(edgeSvg(e));
    for (const l of e.labels || []) {
      body.push(`<rect x="${l.x - 2}" y="${l.y - 1}" width="${l.width + 4}" height="${l.height + 2}" rx="3" fill="#fff"/>`
        + `<text x="${l.x + l.width / 2}" y="${l.y + 12}" class="elab" text-anchor="middle">${esc(l.text)}</text>`);
    }
  }
  for (const n of res.children) {
    const s = n.id, c = COLORS[s];
    const t = tablesOf(s), v = viewsOf(s);
    body.push(`<g transform="translate(${n.x},${n.y})"><rect width="${n.width}" height="${n.height}" rx="8" fill="#fff" stroke="${c}" stroke-width="2"/>`
      + `<path d="M0,8 a8,8 0 0 1 8,-8 h${n.width - 16} a8,8 0 0 1 8,8 v24 h-${n.width} z" fill="${c}"/>`
      + `<text x="12" y="21" class="oth">${esc(s)}</text>`
      + `<text x="12" y="56" class="ot">${t.length} tables · ${v.length} views</text>`
      + `<text x="12" y="76" class="ot">${t.filter((x) => x.hypertable).length} hypertables · ${v.filter((x) => x.cagg).length} continuous aggregates</text>`
      + `<text x="12" y="96" class="ot">${model.foreign_keys.filter((f) => f.from.startsWith(s + ".")).length} foreign keys (from this schema)</text></g>`);
  }
  const W = Math.ceil(res.width) + 80, H = Math.ceil(res.height) + 40;
  const legend = `<div class="legend"><h3>Legend</h3>
    <p><span class="k" style="background:#f4c542">PK</span> primary key <span class="k" style="background:#9cc3f0">FK</span> foreign key
    <span class="k" style="background:#f4c542">PF</span> both <span class="k" style="background:#d9dde3">UQ</span> unique
    <span class="nn">●</span> NOT NULL <span class="k" style="background:#63F8BA;border-radius:7px">hypertable</span> TimescaleDB hypertable</p>
    <p>Lines run from the referenced (parent) table, marked with a bar, to the referencing (child) table, marked with a crow's foot.
    Referenced tables in other schemas appear as dashed boxes. Arrows on this page count foreign keys between schemas.</p>
    <p>DDL for every object is in <b>BESS DESIGN/Database/DDL</b> (00_create_all.sql runs everything in order).</p></div>`;
  const totals = `${rels.filter((r) => r.kind === "table").length} tables · ${rels.filter((r) => r.kind === "view").length} views · ${model.foreign_keys.length} foreign keys`;
  return {
    css: `@page ov { size: 1400px 1000px; margin: 0 }`,
    html: `<section class="page" style="page:ov;width:1400px;height:1000px">
      <header style="border-color:#1f2937"><h1>BESS database — entity relationship diagrams</h1>
      <p>Database <b>${esc(model.database)}</b> · generated ${esc(model.generated)} · ${totals}</p></header>
      <svg width="${Math.min(W, 1360)}" height="${Math.min(H, 620)}" viewBox="-40 -10 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${body.join("")}</svg>
      ${legend}</section>`,
  };
}

// ---------------------------------------------------------------- indexes (tables, views)
function indexPages() {
  const rowsT = [], rowsV = [];
  for (const s of model.schemas) {
    for (const t of tablesOf(s)) {
      const fk = model.foreign_keys.filter((f) => f.from === `${t.schema}.${t.name}`).map((f) => f.to.replace(s + ".", "")).join(", ");
      rowsT.push(`<tr><td><span class="dot" style="background:${COLORS[s]}"></span>${esc(s)}</td><td><b>${esc(t.name)}</b>${t.hypertable ? ' <span class="k" style="background:#63F8BA;border-radius:7px">hypertable</span>' : ""}</td>`
        + `<td class="n">${t.columns.length}</td><td>${esc(t.columns.filter((c) => c.pk).map((c) => c.name).join(", "))}</td><td>${esc(fk)}</td><td>${esc(t.comment || "")}</td></tr>`);
    }
    for (const v of viewsOf(s)) {
      rowsV.push(`<tr><td><span class="dot" style="background:${COLORS[s]}"></span>${esc(s)}</td><td><b>${esc(v.name)}</b></td><td>${v.cagg ? "continuous aggregate" : "view"}</td>`
        + `<td class="n">${v.columns.length}</td><td>${esc((v.sources || []).map((x) => x.replace(s + ".", "")).join(", "))}</td></tr>`);
    }
  }
  const per = 48, pages = [];
  for (let i = 0; i < rowsT.length; i += per) {
    pages.push(`<section class="page doc" style="page:a3"><header><h1>Table index ${rowsT.length > per ? `(${i / per + 1}/${Math.ceil(rowsT.length / per)})` : ""}</h1></header>
      <table class="idx"><thead><tr><th>Schema</th><th>Table</th><th>Cols</th><th>Primary key</th><th>References</th><th>Comment</th></tr></thead><tbody>${rowsT.slice(i, i + per).join("")}</tbody></table></section>`);
  }
  for (let i = 0; i < rowsV.length; i += per) {
    pages.push(`<section class="page doc" style="page:a3"><header><h1>View index</h1><p>Views and TimescaleDB continuous aggregates, with the relations each one reads from.</p></header>
      <table class="idx"><thead><tr><th>Schema</th><th>View</th><th>Type</th><th>Cols</th><th>Reads from</th></tr></thead><tbody>${rowsV.slice(i, i + per).join("")}</tbody></table></section>`);
  }
  return { css: `@page a3 { size: 1587px 1123px; margin: 0 }`, html: pages.join("") };
}

// ---------------------------------------------------------------- document
const parts = [await overviewPage()];
for (const [i, s] of model.schemas.entries()) parts.push(await schemaPage(s, i));
parts.push(indexPages());

const html = `<!doctype html><html><head><meta charset="utf-8"><title>BESS ERD</title><style>
${parts.map((p) => p.css).join("\n")}
html,body{margin:0;padding:0;background:#fff;font-family:"Segoe UI",Arial,sans-serif;color:#1f2937}
.page{break-after:page;overflow:hidden;box-sizing:border-box;padding:24px 20px 0}
.page.doc{width:1587px;height:1123px;padding:30px 40px}
header{border-left:6px solid #1f2937;padding:2px 0 6px 14px;margin-bottom:10px}
header h1{margin:0;font-size:26px} header p{margin:3px 0 0;font-size:14px;color:#4b5563} .stats{color:#6b7280!important;font-size:13px!important}
svg text{font-family:"Segoe UI",Arial,sans-serif}
.th{font-size:12.5px;font-weight:700;fill:#fff} .badge{font-size:9px;font-weight:700;fill:#0b3d2e;text-anchor:middle}
.c{font-size:${FONT}px;fill:#1f2937} .cpk{font-size:${FONT}px;fill:#111;font-weight:700} .t{font-size:10px;fill:#6b7280}
.key{font-size:8px;font-weight:700;fill:#1f2937;text-anchor:middle} .nn{font-size:7px;fill:#9aa3ad}
.gs{font-size:9.5px;fill:#6b7280} .gt{font-size:12px;font-weight:700;fill:#374151}
.edge{fill:none;stroke:#7b8794;stroke-width:1.1}
.oth{font-size:15px;font-weight:700;fill:#fff} .ot{font-size:13px;fill:#374151} .elab{font-size:11px;font-weight:700;fill:#374151}
.legend{margin:6px 30px;font-size:13px;color:#374151} .legend h3{margin:0 0 4px}
.k{display:inline-block;padding:0 5px;font-size:10px;font-weight:700;border-radius:2px;margin:0 3px 0 10px}
table.idx{border-collapse:collapse;width:100%;font-size:11.5px} .idx th{background:#1f2937;color:#fff;text-align:left;padding:4px 6px}
.idx td{border-bottom:1px solid #e5e7eb;padding:2.5px 6px;vertical-align:top} .idx td.n{text-align:right}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
</style></head><body>${parts.map((p) => p.html).join("\n")}</body></html>`;
fs.writeFileSync(outPath, html, "utf8");
console.log(`wrote ${outPath} (${(html.length / 1024).toFixed(0)} KB)`);
