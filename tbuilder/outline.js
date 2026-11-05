// Injected into a copy of an HTML dashboard and run by headless Chrome.
// Collects visual building blocks with their rendered boxes and writes them as JSON
// into <script id="tb-outline" type="application/json">.
(function () {
  const box = (e) => {
    const b = e.getBoundingClientRect();
    return [Math.round(b.left + scrollX), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)];
  };
  const visible = (e) => {
    const b = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return b.width > 0 && b.height > 0 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity !== 0;
  };
  const text = (e) => (e.innerText || e.textContent || "").replace(/\s+/g, " ").trim();
  // Colors as #RRGGBB (decisions/133): any CSS color the page or a chart library gives; transparent / unparseable -> null.
  const hexOf = (c) => {
    if (typeof c !== "string" || !c || c === "none") return null;
    const probe = document.createElement("span");
    probe.style.color = c;
    if (!probe.style.color) return null;
    document.body.appendChild(probe);
    const m = getComputedStyle(probe).color.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?/);
    probe.remove();
    if (!m || (m[4] !== undefined && +m[4] === 0)) return null;
    return "#" + [m[1], m[2], m[3]].map((x) => (+x).toString(16).padStart(2, "0")).join("").toUpperCase();
  };
  const fsize = (e) => parseFloat(getComputedStyle(e).fontSize) || 0;
  // a unit after the number is part of it: '40.2 h', '35 min', '2.4x' (match.UNITS, decisions/090)
  const NUM = /^[-+−–]?\s?[$€£₽¥]?\s?\d[\d\s.,]*\s?(%|pp|[kKmMbBT]|bn|mn|GW|MW|kW|TWh|GWh|x|×|h|hrs?|mins?|d|ms|s|sec|wks?|mo|yrs?)?\+?$/;
  const all = [...document.body.querySelectorAll("*")].filter((e) => !e.closest("script,style,noscript") && visible(e));

  const out = {
    title: document.title,
    lang: document.documentElement.getAttribute("lang") || "",  // the workbook's locale (decisions/085)
    page: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    palette: {}, fonts: {}, headings: [], numbers: [], svgs: [], canvases: [], tables: [], bar_groups: [], controls: [],
  };

  // Palette: CSS custom properties on :root that look like colors.
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (_) { continue; }
    for (const r of rules || []) {
      if (r.selectorText && /(^|,)\s*:root\s*(,|$)/.test(r.selectorText)) {
        for (const p of r.style) {
          const v = r.style.getPropertyValue(p).trim();
          if (p.startsWith("--") && /^(#[0-9a-f]{3,8}|rgba?\(|hsla?\()/i.test(v)) out.palette[p] = v;
        }
      }
    }
  }
  out.fonts.body = getComputedStyle(document.body).fontFamily;
  const h1 = document.querySelector("h1");
  if (h1) out.fonts.display = getComputedStyle(h1).fontFamily;

  // Headings: real h1-h6 plus short title-like elements.
  for (const e of all) {
    const t = text(e);
    if (!t || t.length > 90) continue;
    const isH = /^H[1-6]$/.test(e.tagName);
    const titleClass = /(^|[\s_-])(title|heading|header|kicker|label-head|card-title|section-title)([\s_-]|$)/i.test(e.className || "");
    if ((isH || titleClass) && !e.querySelector("h1,h2,h3,h4,h5,h6")) {
      out.headings.push({ tag: e.tagName.toLowerCase(), text: t, font_size: fsize(e), box: box(e) });
    }
  }

  // Big numbers (KPI candidates): leaf-ish elements whose whole text is a number, rendered large.
  for (const e of all) {
    if (e.children.length > 2) continue;
    const t = text(e);
    if (!t || t.length > 24 || !NUM.test(t) || fsize(e) < 20) continue;
    if (e.parentElement && NUM.test(text(e.parentElement)) && fsize(e.parentElement) >= 20 && e.parentElement.children.length <= 2) continue;
    let label = "";
    for (let p = e.parentElement, depth = 0; p && depth < 3 && !label; p = p.parentElement, depth++) {
      const rest = text(p).replace(t, "").trim();
      if (rest && rest.length <= 80) label = rest;
    }
    out.numbers.push({ text: t, font_size: fsize(e), color: getComputedStyle(e).color, label, box: box(e) });
  }

  // SVG / canvas charts.
  for (const s of document.querySelectorAll("svg")) {
    if (!visible(s) || s.closest("svg") !== s) continue;
    const b = box(s);
    if (b[2] < 80 || b[3] < 40) continue;
    const count = (sel) => s.querySelectorAll(sel).length;
    const texts = [...new Set([...s.querySelectorAll("text")].map(text).filter(Boolean))].slice(0, 40);
    out.svgs.push({ box: b, rects: count("rect"), paths: count("path"), lines: count("line,polyline"),
                    circles: count("circle"), texts });
  }
  for (const c of document.querySelectorAll("canvas")) if (visible(c)) out.canvases.push({ box: box(c) });

  // Tables.
  for (const t of document.querySelectorAll("table")) {
    if (!visible(t)) continue;
    const headers = [...t.querySelectorAll("thead th, tr:first-child th")].map(text);
    const body = [...(t.tBodies[0] || t).rows].filter((r) => !r.querySelector("th") || r.cells[0].tagName === "TH" && r.cells.length > 1 && r !== t.rows[0]);
    // Header band and in-cell bar colors as drawn (decisions/079): the first th's own fill or its row's / thead's,
    // its text color; the fills of the inline-sized elements in the body cells (progress bars).
    const fill = (e) => getComputedStyle(e).backgroundColor;
    const clear = (c) => !c || c === "transparent" || /^rgba\(.*,\s*0\)$/.test(c);
    const th = t.querySelector("thead th, tr:first-child th");
    const thFill = th ? [th, th.parentElement, t.tHead].filter(Boolean).map(fill).find((c) => !clear(c)) : null;
    const bars = [...body.flatMap((r) => [...r.querySelectorAll("td [style]")])]
      .filter((e) => /(^|;)\s*width\s*:/i.test(e.getAttribute("style") || "")).map(fill).filter((c) => !clear(c));
    out.tables.push({ box: box(t), headers, n_rows: body.length,
                      row_labels: body.map((r) => text(r.cells[0])).slice(0, 40),
                      sample: body.slice(0, 3).map((r) => [...r.cells].map(text)),
                      header_colors: th ? { background: thFill || null, color: getComputedStyle(th).color } : null,
                      bar_colors: [...new Set(bars)] });
  }

  // CSS bar groups: >=3 siblings whose size comes from inline width/height (div-based bars).
  const sized = (e) => /(^|;)\s*(width|height|flex-basis|flex)\s*:/i.test(e.getAttribute("style") || "");
  // A bar is (nearly) empty: an element holding a chart / table or text in two places is a visual's container.
  const container = (e) => e.querySelector("svg,canvas,table")
    || [...e.querySelectorAll("*")].filter((c) => [...c.childNodes].some((n) => n.nodeType === 3 && n.nodeValue.trim())).length >= 2;
  const seen = new Set();
  for (const parent of all) {
    const kids = [...parent.children].filter(visible);
    if (kids.length < 3) continue;
    const bars = kids.map((k) => (sized(k) ? k : [...k.querySelectorAll("[style]")].find(sized))).filter(Boolean);
    if (bars.length < 3 || bars.length < kids.length * 0.6 || seen.has(parent)) continue;
    if (bars.some(container)) continue;  // sized wrappers of whole visuals (absolute-positioned BI export), not bars (decisions/108)
    const bb = bars.map(box);
    const widths = new Set(bb.map((b) => b[2])), heights = new Set(bb.map((b) => b[3]));
    const orientation = widths.size > heights.size ? "horizontal" : heights.size > widths.size ? "vertical" : "unknown";
    const stacked = parent.getAttribute("style") === null && getComputedStyle(parent).display === "flex"
      && bb.every((b) => b[1] === bb[0][1]) && orientation === "horizontal";
    out.bar_groups.push({ box: box(parent), n: bars.length, orientation: stacked ? "stacked" : orientation,
                          labels: kids.map(text).map((t) => t.slice(0, 50)),
                          colors: bars.map((b) => getComputedStyle(b).backgroundColor) });
    [parent, ...parent.querySelectorAll("*")].forEach((d) => seen.add(d));
  }

  // Large images (static maps, chart screenshots).
  out.images = [];
  for (const img of document.querySelectorAll("img")) {
    const b = box(img);
    if (visible(img) && b[2] >= 150 && b[3] >= 150) out.images.push({ box: b, src: img.getAttribute("src"), alt: img.alt || "" });
  }

  // Row lists: >=3 same-class siblings, each a row of cells with a number (div-based tables).
  out.lists = [];
  for (const parent of all) {
    if (seen.has(parent) || parent.closest("table")) continue;
    const kids = [...parent.children].filter(visible);
    if (kids.length < 3 || !kids[0].className) continue;
    if (!kids.every((k) => k.className === kids[0].className)) continue;
    const bigNumber = (k) => [...k.querySelectorAll("*")].some((c) => NUM.test(text(c)) && fsize(c) >= 20);
    if (kids.some(bigNumber)) continue; // KPI tiles, handled as numbers
    const rows = kids.map((k) => [...k.querySelectorAll("*")].filter((c) => !c.children.length && text(c)).map(text));
    if (rows.every((r) => r.length >= 2 && r.some((c) => /\d/.test(c)))) {
      out.lists.push({ box: box(parent), rows: rows.slice(0, 30), n: kids.length });
      [...parent.querySelectorAll("*")].forEach((d) => seen.add(d));
    }
  }

  // Every visible text with a digit, with the text around it (reconciliation, decisions/024).
  const textOf = (e) => {
    const parts = [], w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const p = n.parentElement;
      if (p && !p.closest("script,style,noscript,select,title,desc") && visible(p)) parts.push(n.nodeValue);
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  // A grid drawn in divs (decisions/200): a number-only text outside svg and table belongs to the smallest element
  // holding at least 9 such texts. reconcile_grid pairs them with the labels of that element by position.
  const NUMBER_ONLY = /^[\s\-−+$€£¥(]*[\d.,]+\s*[%)kKmMbB]?\s*$/;
  let gridScopes = [];
  const collectTexts = () => {
  const svgs = [...document.querySelectorAll("svg")].filter((s) => s.closest("svg") === s);
  const texts = [];
  const loose = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const p = n.parentElement, t = n.nodeValue.replace(/\s+/g, " ").trim();
    if (!/\d/.test(t) || !p || p.closest("script,style,noscript,select,title,desc,textarea,#tb-outline") || !visible(p)) continue;
    const item = { text: t, box: box(p), up: [] };
    for (let a = p, depth = 0; a && a !== document.body && depth < 4; a = a.parentElement, depth++) {
      const at = textOf(a);
      if (at.length > 160) break;
      item.up.push(at);
    }
    if (p.getAttribute("title")) item.title = p.getAttribute("title");
    if (getComputedStyle(p).display.startsWith("inline")) item.inline = true;  // part of its parent's sentence (200)
    const td = p.closest("td,th"), tr = td && td.parentElement, table = td && td.closest("table");
    if (td && table) {
      const head = table.tHead ? table.tHead.rows[0] : table.rows[0];
      // A rank column ('1' before 'Laptop') is not the row's name.
      const named = /^\d+$/.test(text(tr.cells[0])) && tr.cells[1] ? tr.cells[1] : tr.cells[0];
      item.cell = { row: tr === head ? "" : text(named),
                    col: head && head.cells[td.cellIndex] ? text(head.cells[td.cellIndex]) : "" };
      // The group row above ('East' over its rows): a single cell spanning the table. Its own total row ('East total')
      // closes it: the row after that ('Grand total') belongs to no group.
      const between = [];
      for (let g = tr.previousElementSibling; g; g = g.previousElementSibling) {
        if (g.cells.length === 1 && g.cells[0].colSpan > 1) {
          const name = text(g.cells[0]);
          if (!between.some((label) => label.startsWith(name))) item.cell.group = name;
          break;
        }
        between.push(text(g.cells[0]));
      }
    }
    let svg = p.closest("svg");
    while (svg && svg.parentElement && svg.parentElement.closest("svg")) svg = svg.parentElement.closest("svg");
    if (svg) {
      item.svg = svgs.indexOf(svg);
      const cx = item.box[0] + item.box[2] / 2;
      const near = [...svg.querySelectorAll("text")].filter((x) => /[A-Za-z]/.test(text(x)) && visible(x))
        .map((x) => [Math.abs(box(x)[0] + box(x)[2] / 2 - cx), text(x)]).sort((a, b) => a[0] - b[0])[0];
      if (near && near[0] <= 6) item.svg_label = near[1];
    }
    if (!svg && !item.cell && NUMBER_ONLY.test(t)) loose.push([p, item]);
    texts.push(item);
  }
  gridScopes = [];
  for (const [p, item] of loose) {
    let a = p.parentElement;
    while (a && a !== document.body && loose.filter(([q]) => a.contains(q)).length < 9) a = a.parentElement;
    if (!a || a === document.body) continue;
    if (!gridScopes.includes(a)) gridScopes.push(a);
    item.grid = gridScopes.indexOf(a);
  }
  return texts;
  };
  // The texts of each grid scope that are not a bare number, the row and column names among them (decisions/200).
  const collectGridLabels = () => gridScopes.flatMap((scope, grid) => {
    const out = [];
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const p = n.parentElement, t = n.nodeValue.replace(/\s+/g, " ").trim();
      if (t && t.length <= 40 && !NUMBER_ONLY.test(t) && visible(p) && !p.closest("svg,table")) out.push({ grid, text: t, box: box(p) });
    }
    return out;
  });

  // Numbers a <canvas> chart draws: no text in the DOM, so they are read from the chart's data (decisions/058):
  // a Chart.js or ECharts instance (whatever the config came from: an inline <script>, window.*, a fetch), or
  // data-labels + data-values (JSON) on the canvas or a parent. A value as a string with 12 significant digits.
  const num = (v) => {
    if (typeof v !== "number" || !isFinite(v)) return null;
    const s = String(+v.toPrecision(12));
    return /e/i.test(s) ? null : s;
  };
  const headingOf = (c) => {
    for (let a = c.parentElement, depth = 0; a && a !== document.body && depth < 4; a = a.parentElement, depth++) {
      const h = [...a.querySelectorAll("h1,h2,h3,h4,h5,h6,[class*=title],[class*=heading]")].find((x) => !x.contains(c) && text(x));
      if (h) return text(h).slice(0, 160);
    }
    return "";
  };
  const fromChartJs = (inst) => {
    const data = inst.data || (inst.config && inst.config.data) || {}, opts = inst.options || {};
    const t = (opts.plugins && opts.plugins.title && opts.plugins.title.text) || (opts.title && opts.title.text) || "";
    const labels = data.labels || [], points = [];
    (data.datasets || []).forEach((ds) => (ds.data || []).forEach((v, i) => {
      let label = labels[i];
      if (v && typeof v === "object" && !Array.isArray(v)) {
        if (label === undefined && v.x !== undefined) label = v.x;
        v = v.y !== undefined ? v.y : v.value;
      }
      const s = num(v);
      if (s !== null) points.push({ label: label === undefined ? "" : String(label), series: String(ds.label || ""), value: s });
    }));
    const colors = {};  // series name -> color (explicit colors only, decisions/133)
    (data.datasets || []).forEach((ds) => {
      const bg = ds.backgroundColor;
      if (Array.isArray(bg)) bg.forEach((c, i) => { const h = hexOf(c); if (h && labels[i] !== undefined) colors[String(labels[i])] = h; });
      else { const h = hexOf(bg) || hexOf(ds.borderColor); if (h && ds.label) colors[String(ds.label)] = h; }
    });
    const sets = data.datasets || [], one = sets.length === 1 && !Array.isArray(sets[0].backgroundColor) ? sets[0] : null;
    const oneColor = one && (hexOf(one.backgroundColor) || hexOf(one.borderColor));  // a single series: its color is the measure's (decisions/135)
    return { lib: "chart.js", type: (inst.config && inst.config.type) || "", title: [].concat(t).join(" "), points, colors,
             single: oneColor ? { name: String(one.label || ""), color: oneColor } : null };
  };
  const fromECharts = (inst) => {
    const o = inst.getOption() || {}, points = [];
    const cat = [...(o.xAxis || []), ...(o.yAxis || [])].find((a) => a.type === "category" && a.data);
    const labels = cat ? cat.data.map((d) => (d && typeof d === "object" ? d.value : d)) : [];
    (o.series || []).forEach((sr) => (sr.data || []).forEach((d, i) => {
      let label = labels[i], v = d;
      if (d && typeof d === "object" && !Array.isArray(d)) { if (d.name !== undefined) label = d.name; v = d.value; }
      if (Array.isArray(v)) { if (label === undefined) label = v[0]; v = v[v.length - 1]; }
      const s = num(v);
      if (s !== null) points.push({ label: label === undefined ? "" : String(label), series: String(sr.name || ""), value: s });
    }));
    const palette = [].concat(o.color || []), colors = {};  // series / pie slice name -> color (decisions/133)
    const paint = (name, own, i) => {
      const h = hexOf(typeof own === "string" ? own : palette.length ? palette[i % palette.length] : null);
      if (h && name) colors[String(name)] = h;
    };
    (o.series || []).forEach((sr, si) => {
      const named = (sr.data || []).filter((d) => d && typeof d === "object" && !Array.isArray(d) && d.name !== undefined);
      if (sr.type === "pie" || (named.length && !sr.name)) named.forEach((d, i) => paint(d.name, d.itemStyle && d.itemStyle.color, i));
      else if (sr.name) paint(sr.name, (sr.itemStyle && sr.itemStyle.color) || (sr.lineStyle && sr.lineStyle.color), si);
    });
    let single = null;  // one series with a plain color (or the palette's first): the measure's color (decisions/135)
    const sr0 = (o.series || []).length === 1 ? o.series[0] : null;
    if (sr0 && !["pie", "heatmap", "treemap", "sunburst"].includes(sr0.type) && !(sr0.data || []).some((d) => d && d.name !== undefined && !Array.isArray(d))) {
      const own = [sr0.itemStyle && sr0.itemStyle.color, sr0.lineStyle && sr0.lineStyle.color].find((c) => c !== undefined);
      const h = hexOf(own !== undefined ? (typeof own === "string" ? own : null) : palette[0]);
      if (h) single = { name: String(sr0.name || ""), color: h };
    }
    const vm = [].concat(o.visualMap || []).map((v) => v && v.inRange ? [].concat(v.inRange.color || []).map(hexOf).filter(Boolean) : [])
      .find((c) => c.length >= 2);  // color by measure: the ends of the scale, low -> high
    return { lib: "echarts", type: ((o.series || [])[0] || {}).type || "", title: (((o.title || [])[0] || {}).text) || "", points, colors,
             single, scale: vm || null };
  };
  const fromAttributes = (el) => {
    try {
      const labels = JSON.parse(el.dataset.labels), values = JSON.parse(el.dataset.values), points = [];
      const series = Array.isArray(values) ? { "": values } : values;
      for (const [name, vals] of Object.entries(series)) vals.forEach((v, i) => {
        const s = num(v);
        if (s !== null) points.push({ label: String(labels[i] === undefined ? "" : labels[i]), series: name, value: s });
      });
      return { lib: "data-attributes", type: "", title: el.dataset.title || "", points };
    } catch (_) { return null; }
  };
  const chartOf = (c) => {
    const C = window.Chart;
    if (C) {
      const inst = C.getChart ? C.getChart(c) : Object.values(C.instances || {}).find((i) => i && i.canvas === c);
      if (inst) return fromChartJs(inst);
    }
    for (let el = c; el && el !== document.body; el = el.parentElement) {
      const inst = window.echarts && window.echarts.getInstanceByDom && window.echarts.getInstanceByDom(el);
      if (inst) return fromECharts(inst);
      if (el.dataset && el.dataset.labels && el.dataset.values) return fromAttributes(el);
    }
    return null;
  };
  const canvasEls = [...document.querySelectorAll("canvas")].filter(visible);
  const collectCharts = () => canvasEls.map((c, i) => {
    const ch = chartOf(c);
    return ch && ch.points.length ? { canvas: i, heading: headingOf(c), ...ch } : null;
  }).filter(Boolean);

  // Controls that look like filters.
  const controlEls = [];
  for (const sel of document.querySelectorAll("select")) {
    if (!visible(sel)) continue;
    const label = (sel.labels && sel.labels[0] && text(sel.labels[0])) || sel.getAttribute("aria-label") || "";
    out.controls.push({ kind: "select", box: box(sel), label, options: [...sel.options].map((o) => o.text).slice(0, 30),
      selected: [...sel.selectedOptions].map((o) => o.text), multiple: sel.multiple });  // the page's state at load (default)
    controlEls.push(sel);
  }
  const active = (b) => b.getAttribute("aria-pressed") === "true" || b.getAttribute("aria-selected") === "true"
    || /(^|\s)(active|selected|is-active|on|current)(\s|$)/.test(b.className || "");
  for (const parent of all) {
    const btns = [...parent.children].filter((k) => k.tagName === "BUTTON" || k.getAttribute("role") === "tab");
    if (btns.length >= 2) {
      out.controls.push({ kind: "buttons", box: box(parent), options: btns.map(text).slice(0, 30),
                          selected: btns.filter(active).map(text) });
      controlEls.push(btns);
    }
  }

  // Static slicers (decisions/112): a short caption and the value(s) it holds, in plain markup (no select, no button):
  // <div><span>Region</span><span>All</span></div> or <div><span>Region</span><span>North</span><span>South</span>...</div>.
  // Whether the caption/values name a data column is decided against the data (match.py), not here.
  const leaf = (e) => e.children.length === 0 && text(e);
  const chipsOf = (rest) => rest.length === 1 && rest[0].children.length >= 2 ? [...rest[0].children] : rest;
  const taken = new Set(out.controls.map((c) => c.box.join()));
  for (const e of all) {
    if (e.closest("svg,table,canvas") || e.children.length < 2 || e.children.length > 40 || /^(SELECT|BUTTON|A|TABLE|UL|OL|SVG|svg)$/.test(e.tagName)) continue;
    if (e.querySelector("select,button,input,svg,canvas,table,[role=tab]") || text(e).length > 160) continue;
    const [head, ...rest] = [...e.children].filter((k) => visible(k) && (text(k) || k.children.length));  // not a bare arrow/icon
    if (!head || !rest.length || !leaf(head) || text(head).length > 24) continue;
    const chips = chipsOf(rest);
    if (!chips.every(leaf) || chips.some((c) => text(c).length > 30)) continue;
    const options = chips.map(text);
    if (new Set(options).size !== options.length) continue;
    const b = box(e);
    if (taken.has(b.join())) continue;
    taken.add(b.join());
    const on = options.length === 1 ? options : chips.filter(active).map(text);
    out.controls.push({ kind: "slicer", box: b, label: text(head), options: options.slice(0, 30), selected: on, multiple: on.length > 1 });
    controlEls.push([]);
  }

  // Lines drawn in svg (decisions/123): the vertices of each open polyline / M-L path in page pixels, plus the
  // horizontal rules (gridlines) of the same svg: a value axis is read from them when the line has no labels.
  const collectLines = () => {
    const out = [];
    const svgs = [...document.querySelectorAll("svg")].filter((s) => s.closest("svg") === s);
    const page = (el, x, y) => {
      const m = el.getScreenCTM();
      if (!m) return null;
      return [+(m.a * x + m.c * y + m.e + scrollX).toFixed(2), +(m.b * x + m.d * y + m.f + scrollY).toFixed(2)];
    };
    svgs.forEach((s, i) => {
      if (!visible(s)) return;
      const item = { svg: i, polylines: [], hlines: [], colors: [], lib: s.closest(".js-plotly-plot") ? "plotly" : "" };
      for (const el of s.querySelectorAll("polyline,path")) {
        if (!visible(el) || (el.getAttribute("fill") || getComputedStyle(el).fill) !== "none") continue;
        let pts = [];
        if (el.tagName === "polyline") {
          pts = [...el.points].map((p) => [p.x, p.y]);
        } else {
          const d = el.getAttribute("d") || "";
          if (!/^\s*M[^A-Za-z]*(L[^A-Za-z]*)+$/.test(d)) continue;  // absolute M / L only: no curves, no closed areas
          pts = (d.match(/-?\d*\.?\d+(?:e[-+]?\d+)?\s*[, ]\s*-?\d*\.?\d+(?:e[-+]?\d+)?/gi) || [])
            .map((q) => q.split(/[\s,]+/).map(Number));
        }
        const got = pts.map((p) => page(el, p[0], p[1]));
        if (got.length >= 3 && got.every(Boolean)) { item.polylines.push(got); item.colors.push(hexOf(getComputedStyle(el).stroke)); }
      }
      for (const el of s.querySelectorAll("line")) {
        if (!visible(el)) continue;
        const a = page(el, el.x1.baseVal.value, el.y1.baseVal.value), b = page(el, el.x2.baseVal.value, el.y2.baseVal.value);
        if (a && b && Math.abs(a[1] - b[1]) < 0.5 && Math.abs(a[0] - b[0]) >= 30) item.hlines.push(a[1]);
      }
      if (item.polylines.length) out.push(item);
    });
    return out;
  };

  // Texts of svg charts (decisions/127): the category labels of a heatmap's axes name its cells by position, so every
  // visible svg <text> with its page box is kept; reconcile_grid pairs the numbers with them.
  const collectSvgLabels = () => {
    const svgs = [...document.querySelectorAll("svg")].filter((s) => s.closest("svg") === s);
    const out = [];
    svgs.forEach((s, i) => {
      if (!visible(s)) return;
      for (const el of [...s.querySelectorAll("text")].slice(0, 400)) {
        const t = text(el);
        if (t && visible(el)) out.push({ svg: i, text: t, box: box(el) });
      }
    });
    return out;
  };

  // Legend swatches (decisions/133): a small filled square / dot (or a short line) with a caption to its right, in svg
  // (Plotly's legend too) or plain markup. Two or more of one size, two of them aligned, make a legend (match.py); a
  // chart's own small bars (other sizes) with labels do not. The caption is a value of the series' dimension.
  const collectSwatches = () => {
    const found = [];
    const small = (b) => (b[2] >= 4 && b[3] >= 4 && b[2] <= 22 && b[3] <= 22 && b[2] / b[3] >= 0.5 && b[2] / b[3] <= 2)
      || (b[3] <= 4 && b[2] >= 8 && b[2] <= 50);
    const svgs = [...document.querySelectorAll("svg")].filter((s) => s.closest("svg") === s && visible(s));
    svgs.forEach((s, si) => {
      const texts = [...s.querySelectorAll("text")].filter(visible).map((t) => ({ t: text(t), b: box(t) })).filter((t) => t.t && t.t.length <= 40);
      for (const e of s.querySelectorAll("rect,circle,path,line,polyline,ellipse")) {
        if (!visible(e)) continue;
        const b = box(e);
        if (!small(b)) continue;
        const cs = getComputedStyle(e);
        const color = hexOf(cs.fill) || (parseFloat(cs.strokeWidth) > 0 ? hexOf(cs.stroke) : null);
        if (!color) continue;
        const cy = b[1] + b[3] / 2;
        const cap = texts.filter((t) => t.b[0] >= b[0] + b[2] - 2 && t.b[0] - (b[0] + b[2]) <= 30 && Math.abs(t.b[1] + t.b[3] / 2 - cy) <= 8)
          .sort((x, y) => x.b[0] - y.b[0])[0];
        if (cap) found.push({ where: "svg" + si, name: cap.t, color, box: b });
      }
    });
    for (const e of all) {
      if (e.closest("svg,canvas") || e.children.length || text(e)) continue;
      const b = box(e);
      if (!small(b)) continue;
      const color = hexOf(getComputedStyle(e).backgroundColor);
      if (!color) continue;
      let name = "";
      const nx = e.nextElementSibling;
      if (nx && text(nx) && text(nx).length <= 40) {
        const nb = box(nx);
        if (nb[0] - (b[0] + b[2]) <= 30 && nb[0] >= b[0] && Math.abs(nb[1] + nb[3] / 2 - (b[1] + b[3] / 2)) <= 10) name = text(nx);
      }
      if (!name && e.parentElement && text(e.parentElement).length <= 40) name = text(e.parentElement);
      if (name) found.push({ where: "html", name, color, box: b });
    }
    // Legend without swatches (decisions/135): the caption itself is colored, or a colored glyph (a dot, a dash) leads it.
    const chroma = (h) => { const n = parseInt(h.slice(1), 16); const r = n >> 16 & 255, g = n >> 8 & 255, bl = n & 255; return (Math.max(r, g, bl) - Math.min(r, g, bl)) / 255; };
    const GLYPH = /^([●■◆▬—─━•○▪▮◼⬤]+)\s*(.*)$/;
    const cands = [];
    for (const e of all) {
      if (e.children.length || e.closest("svg,canvas,select,button,a,th,td,h1,h2,h3,h4,h5,h6")) continue;
      const t = text(e);
      if (!t || t.length > 40) continue;
      const color = hexOf(getComputedStyle(e).color);
      if (!color || chroma(color) < 0.2) continue;
      let name = t;
      const m = t.match(GLYPH);
      if (m) {
        const nx = e.nextElementSibling;
        name = m[2] || (nx && text(nx) && text(nx).length <= 40 ? text(nx) : "");
      }
      if (name) cands.push({ e, name, color, box: box(e) });
    }
    const roots = [];
    for (const c of cands) {  // the nearest ancestor that holds another candidate is the legend
      let a = c.e.parentElement;
      for (let d = 0; a && a !== document.body && d < 3; a = a.parentElement, d++) if (cands.some((x) => x !== c && a.contains(x.e))) break;
      if (!a) continue;
      if (!roots.includes(a)) roots.push(a);
      found.push({ where: "text", group: roots.indexOf(a), name: c.name, color: c.color, box: c.box });
    }
    return found;
  };
  out.swatches = collectSwatches();

  // Colors of the marks themselves (decisions/135): the color of a single series (no legend to read it from) and the
  // ends of a color-by-measure scale (heatmap, colorbar, gradient). Libraries give them from the instance, plain svg /
  // markup from the drawn shapes.
  const lum = (h) => { const n = parseInt(h.slice(1), 16); return 0.2126 * (n >> 16 & 255) + 0.7152 * (n >> 8 & 255) + 0.0722 * (n & 255); };
  const collectPaints = () => {
    const res = [];
    out.charts.forEach((ch) => {
      if (ch.single) res.push({ kind: "single", source: ch.lib, name: ch.single.name, color: ch.single.color, mark: ch.type, heading: ch.heading });
      if (ch.scale) res.push({ kind: "scale", source: ch.lib, colors: ch.scale, mark: ch.type, heading: ch.heading });
    });
    const scaleOf = (cs) => Array.isArray(cs) ? cs.map((q) => hexOf(Array.isArray(q) ? q[1] : q)).filter(Boolean) : [];
    document.querySelectorAll(".js-plotly-plot").forEach((gd) => {
      if (!visible(gd)) return;
      const full = gd._fullData || [], heading = headingOf(gd), drawn = [];
      (gd.data || []).forEach((tr, i) => {
        if (tr.visible === false || tr.visible === "legendonly") return;
        const f = full[i] || {}, mk = tr.marker || {}, fm = f.marker || {};
        if (["heatmap", "contour", "histogram2d"].includes(tr.type)) {
          const c = scaleOf(tr.colorscale).length ? scaleOf(tr.colorscale) : scaleOf(f.colorscale);
          if (c.length >= 2) res.push({ kind: "scale", source: "plotly", colors: c, mark: tr.type, heading });
          return;
        }
        if (Array.isArray(mk.color)) {  // markers colored by a measure
          const c = scaleOf(mk.colorscale).length ? scaleOf(mk.colorscale) : scaleOf(fm.colorscale);
          if (c.length >= 2) res.push({ kind: "scale", source: "plotly", colors: c, mark: tr.type || "scatter", heading });
          return;
        }
        const pick = [mk.color, (tr.line || {}).color, fm.color, (f.line || {}).color].find((c) => typeof c === "string" && hexOf(c));
        if (pick) drawn.push({ name: String(tr.name || ""), color: hexOf(pick), mark: tr.type || "scatter" });
      });
      if (drawn.length === 1) res.push({ kind: "single", source: "plotly", heading, ...drawn[0] });
    });
    document.querySelectorAll("svg").forEach((s) => {
      if (s.closest("svg") !== s || !visible(s) || s.closest(".js-plotly-plot")) return;
      const sb = box(s), fills = {};
      let n = 0;
      for (const e of s.querySelectorAll("rect,path")) {
        if (!visible(e)) continue;
        const b = box(e);
        if (b[2] * b[3] >= sb[2] * sb[3] * 0.6) continue;  // a background
        const c = hexOf(getComputedStyle(e).fill);
        if (!c || lum(c) >= 252) continue;
        fills[c] = (fills[c] || 0) + 1;
        n++;
      }
      const names = Object.keys(fills);
      if (names.length >= 6 && n >= 6) {  // cells painted by value: the ends are the lightest and the darkest
        const sorted = names.sort((x, y) => lum(y) - lum(x));
        res.push({ kind: "scale", source: "svg", colors: [sorted[0], sorted[sorted.length - 1]], mark: "cells", heading: headingOf(s) });
      } else if (n >= 3) {
        const top = names.sort((x, y) => fills[y] - fills[x])[0];
        if (fills[top] >= 0.6 * n) res.push({ kind: "single", source: "svg", name: "", color: top, mark: "bar", heading: headingOf(s) });
      }
    });
    const svgEls = [...document.querySelectorAll("svg")].filter((s) => s.closest("svg") === s);
    out.lines.forEach((item) => {
      const cs = [...new Set(item.colors)].filter(Boolean);
      if (!item.lib && cs.length === 1) res.push({ kind: "single", source: "svg", name: "", color: cs[0], mark: "line", heading: svgEls[item.svg] ? headingOf(svgEls[item.svg]) : "" });
    });
    for (const g of document.querySelectorAll("linearGradient")) {
      const stops = [...g.querySelectorAll("stop")].map((st) => hexOf(getComputedStyle(st).stopColor)).filter(Boolean);
      const user = g.id && [...document.querySelectorAll("[fill]")].find((e) => (e.getAttribute("fill") || "").includes("#" + g.id) && visible(e));
      if (user && new Set(stops).size >= 2) res.push({ kind: "scale", source: "svg", colors: stops, mark: "gradient", heading: headingOf(user.closest("svg") || user) });
    }
    for (const e of all) {  // a CSS gradient strip (a colorbar); stripes (px stops) and fades into transparent are not
      if (e.closest("svg")) continue;
      const bg = getComputedStyle(e).backgroundImage;
      if (!/^linear-gradient\(/.test(bg) || /\d(\.\d+)?px/.test(bg.replace(/^linear-gradient\([^,]*,/, ""))) continue;
      const b = box(e);
      if (Math.min(b[2], b[3]) > 30 || Math.max(b[2], b[3]) < 40) continue;
      if ([...e.childNodes].some((nd) => nd.nodeType === 3 && nd.textContent.trim())) continue;
      const toks = bg.match(/rgba?\([^)]*\)/g) || [];
      if (toks.some((t) => /rgba\(.*,\s*0\)/.test(t))) continue;
      const cs = toks.map(hexOf).filter(Boolean);
      if (new Set(cs).size >= 2) res.push({ kind: "scale", source: "css", colors: cs, mark: "gradient", heading: headingOf(e) });
    }
    return res;
  };

  // Click handlers (decisions/174): elements the page's scripts gave a 'click' listener (the hook html_outline puts
  // before them records each one) or an onclick attribute, grouped by tag + class + heading. A control (button, link, tab,
  // form field) switches pages or parameters; anything else (a bar, a row label, a cell) is a click on the data:
  // a dashboard action. A chart library's own listener on its canvas / drag layer is not one.
  const collectClicks = () => {
    const els = new Set([...(window.__tbClicks || [])].filter((e) => e instanceof Element && e.isConnected));
    document.querySelectorAll("[onclick]").forEach((e) => els.add(e));
    const groups = new Map();
    const delegated = [...(window.__tbClicks || [])].some((e) => e === document || e === window || e === document.body);
    for (const e of els) {
      if (e === document.body || e === document.documentElement || !visible(e)) continue;
      if (e.tagName === "CANVAS" || e.querySelector("canvas") || /drag/i.test(e.getAttribute("class") || "")) continue;
      const control = !!e.closest("button,a[href],select,input,textarea,label,option,[role=tab],[role=button],[role=link],[role=menuitem]");
      const cls = (e.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean).sort().join(".");
      const heading = headingOf(e);
      const key = `${e.tagName.toLowerCase()}.${cls}|${control}|${heading}`;
      if (!groups.has(key)) groups.set(key, { tag: e.tagName.toLowerCase(), cls, control, n: 0, values: [], data: [], boxes: [], heading });
      const g = groups.get(key);
      g.n++;
      const v = text(e).slice(0, 60);
      if (v && g.values.length < 12 && !g.values.includes(v)) g.values.push(v);
      for (const a of e.getAttributeNames()) if (a.startsWith("data-") && !g.data.includes(a)) g.data.push(a);
      g.boxes.push(box(e));
    }
    return { delegated, groups: [...groups.values()] };
  };

  const finish = () => {
    const node = document.createElement("script");
    node.type = "application/json";
    node.id = "tb-outline";
    node.textContent = JSON.stringify(out);
    document.body.appendChild(node);
  };
  const first = { texts: collectTexts(), charts: collectCharts() };
  out.texts = first.texts;
  out.svg_labels = collectSvgLabels();
  out.grid_labels = collectGridLabels();
  out.charts = first.charts;
  out.lines = collectLines();
  out.paints = collectPaints();
  out.clicks = collectClicks();
  out.canvases.forEach((c, i) => { c.data = first.charts.some((ch) => ch.canvas === i); });

  // Filter states (decisions/058): every other option of each control, one control at a time from the state at
  // load; the numbers of the page after the switch. Buttons inside a form are not pressed (a submit leaves the page).
  const MAX_STATES = 12, plans = [];
  const signature = (s) => JSON.stringify([s.texts.map((t) => t.text), s.charts.map((c) => c.points.map((p) => p.value))]);
  controlEls.forEach((el, ci) => {
    const c = out.controls[ci];
    if (c.kind === "select") {
      if (el.multiple) return;
      const initial = el.value;
      [...el.options].forEach((o) => {
        if (o.value === initial) return;
        plans.push({ control: ci, option: o.text, apply: () => { el.value = o.value; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); },
                     restore: () => { el.value = initial; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); } });
      });
    } else if (c.kind === "slicer") {  // static markup: nothing to press
    } else if (!el[0].closest("form") && c.selected.length === 1) {  // buttons: which one is pressed must be known
      const on = el.find(active);
      el.forEach((b) => { if (b !== on) plans.push({ control: ci, option: text(b), apply: () => b.click(), restore: () => on.click() }); });
    }
  });
  out.states = [];
  out.states_skipped = Math.max(0, plans.length - MAX_STATES);
  const base = signature(first);
  const step = (i) => {
    if (i >= Math.min(plans.length, MAX_STATES)) return finish();
    const p = plans[i];
    try { p.apply(); } catch (e) { out.states.push({ control: p.control, option: p.option, error: String(e) }); return step(i + 1); }
    setTimeout(() => {
      const got = { texts: collectTexts(), charts: collectCharts(), svg_labels: collectSvgLabels(), grid_labels: collectGridLabels() };
      out.states.push({ control: p.control, option: p.option, same: signature(got) === base, ...got });
      try { p.restore(); } catch (_) { /* the next state starts from wherever the page is */ }
      setTimeout(() => step(i + 1), 100);
    }, 300);
  };
  step(0);
})();
