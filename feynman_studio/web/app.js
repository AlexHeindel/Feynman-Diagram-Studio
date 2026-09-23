"use strict";

const WIDTH = 720;
const HEIGHT = 480;
const KINDS = ["fermion", "photon", "gluon", "scalar", "ghost"];
const MARKERS = ["none", "dot", "open", "filled", "hatched", "crosshatched", "dotted"];
const ARROWS = ["forward", "reverse", "none"];
const STORE = "feynman-diagram-studio.web.v1";
const PROJECTS_STORE = "feynman-diagram-studio.web.projects.v1";
const SETTINGS_STORE = "feynman-diagram-studio.web.settings.v1";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const clone = (value) => JSON.parse(JSON.stringify(value));
const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
const escapeXml = (value) => String(value).replace(/[<>&"']/g, (character) => ({
  "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;",
})[character]);
const niceNumber = (value) => Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
const titleCase = (value) => value.charAt(0).toUpperCase() + value.slice(1);

const state = {
  token: "",
  templates: [],
  projects: [],
  activeProjectId: null,
  latexFormats: [],
  document: null,
  past: [],
  future: [],
  selected: null,
  tool: "select",
  connectionStart: null,
  newKind: "fermion",
  newArrow: "auto",
  newMarker: "dot",
  newMarkerSize: 22,
  loopMode: "single",
  snap: true,
  showGrid: false,
  showFigurePanel: false,
  gridSize: 20,
  theme: "dark",
  libraryWidth: null,
  inspectorWidth: null,
  drag: null,
  sidebarDrag: null,
  autosaveTimer: null,
  latexSource: "",
  standaloneSource: "",
};

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function vertexById(id) {
  return state.document.vertices.find((item) => item.id === id) || null;
}

function edgeById(id) {
  return state.document.edges.find((item) => item.id === id) || null;
}
function annotationById(id) {
  return state.document.annotations.find((item) => item.id === id) || null;
}
function makeAnnotation(type, x, y) {
  return type === "label"
    ? { id: uuid(), type, x, y, text: "label", color: "#172333" }
    : { id: uuid(), type, x1: x, y1: y, x2: Math.min(700, x + 80), y2: y, color: "#172333" };
}
function unsupportedFeatures(documentModel, format) {
  const reasons = [];
  if (["feynmp", "feynmf"].includes(format) && documentModel.edges.some((edge) => edge.bundle > 1)) reasons.push("Quark bundle spacing is not preserved");
  if (format === "feynmf" && (documentModel.edges.some((edge) => edge.color.toUpperCase() !== "#172333" || (edge.momentum && edge.momentum.color.toUpperCase() !== "#172333")) || documentModel.annotations.some((item) => item.color.toUpperCase() !== "#172333"))) reasons.push("Custom colors are not supported by feynMF");
  return reasons;
}

function makeVertex(x, y, label = "", visible = true) {
  return {
    id: uuid(), x, y, label,
    labelX: 0, labelY: y < HEIGHT / 2 ? -30 : 32,
    visible, marker: visible ? "dot" : "none", markerSize: 22,
  };
}

function makeEdge(from, to, kind = "fermion", label = "", curvature = 0) {
  return {
    id: uuid(), from, to, kind, label, curvature,
    labelOffset: -25, labelX: 0, labelY: 0,
    arrow: kind === "fermion" ? "forward" : "none",
    color: "#172333", bundle: 1, bundleSpacing: 14,
    loopSize: 90, loopAngle: -90, circular: false,
  };
}

function bundleOffsets(edge) {
  const count = edge.kind === "fermion" ? edge.bundle : 1;
  return Array.from({ length: count }, (_, index) => (index - (count - 1) / 2) * edge.bundleSpacing);
}

function curve(a, b, curvature, t) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  const control = {
    x: (a.x + b.x) / 2 - (dy / length) * curvature,
    y: (a.y + b.y) / 2 + (dx / length) * curvature,
  };
  const x = (1 - t) ** 2 * a.x + 2 * (1 - t) * t * control.x + t ** 2 * b.x;
  const y = (1 - t) ** 2 * a.y + 2 * (1 - t) * t * control.y + t ** 2 * b.y;
  const tx = 2 * (1 - t) * (control.x - a.x) + 2 * t * (b.x - control.x);
  const ty = 2 * (1 - t) * (control.y - a.y) + 2 * t * (b.y - control.y);
  const magnitude = Math.hypot(tx, ty) || 1;
  return { x, y, tx: tx / magnitude, ty: ty / magnitude, nx: -ty / magnitude, ny: tx / magnitude };
}

function cubic(a, b, c, d, t) {
  const x = (1 - t) ** 3 * a.x + 3 * (1 - t) ** 2 * t * b.x + 3 * (1 - t) * t ** 2 * c.x + t ** 3 * d.x;
  const y = (1 - t) ** 3 * a.y + 3 * (1 - t) ** 2 * t * b.y + 3 * (1 - t) * t ** 2 * c.y + t ** 3 * d.y;
  const dx = 3 * (1 - t) ** 2 * (b.x - a.x) + 6 * (1 - t) * t * (c.x - b.x) + 3 * t ** 2 * (d.x - c.x);
  const dy = 3 * (1 - t) ** 2 * (b.y - a.y) + 6 * (1 - t) * t * (c.y - b.y) + 3 * t ** 2 * (d.y - c.y);
  const magnitude = Math.hypot(dx, dy) || 1;
  return { x, y, tx: dx / magnitude, ty: dy / magnitude, nx: -dy / magnitude, ny: dx / magnitude };
}

function selfLoop(point, size, angleDegrees, t) {
  const angle = angleDegrees * Math.PI / 180;
  const direction = { x: Math.cos(angle), y: Math.sin(angle) };
  const normal = { x: -direction.y, y: direction.x };
  const width = size * 0.58;
  const far = { x: point.x + direction.x * size, y: point.y + direction.y * size };
  const first = { x: point.x + normal.x * width, y: point.y + normal.y * width };
  const second = { x: far.x + normal.x * width, y: far.y + normal.y * width };
  const third = { x: far.x - normal.x * width, y: far.y - normal.y * width };
  const fourth = { x: point.x - normal.x * width, y: point.y - normal.y * width };
  return t <= 0.5 ? cubic(point, first, second, far, t * 2) : cubic(far, third, fourth, point, (t - 0.5) * 2);
}

function circularArc(a, b, side, t) {
  const center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const radius = Math.hypot(b.x - a.x, b.y - a.y) / 2;
  const start = Math.atan2(a.y - center.y, a.x - center.x);
  const sweep = -(side >= 0 ? 1 : -1) * Math.PI;
  const angle = start + sweep * t;
  const tx = -Math.sin(angle) * Math.sign(sweep);
  const ty = Math.cos(angle) * Math.sign(sweep);
  return { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle), tx, ty, nx: -ty, ny: tx };
}

function edgeSample(a, b, edge, t) {
  const isLoop = Math.hypot(b.x - a.x, b.y - a.y) < 0.01;
  return isLoop
    ? selfLoop(a, edge.loopSize, edge.loopAngle, t)
    : edge.circular
      ? circularArc(a, b, edge.curvature || 1, t)
      : curve(a, b, edge.curvature, t);
}

function pathData(values) {
  return values.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(3)},${point.y.toFixed(3)}`).join(" ");
}

function geometry(a, b, edge, laneOffset = 0) {
  const sample = (t) => {
    const point = edgeSample(a, b, edge, t);
    return { ...point, x: point.x + point.nx * laneOffset, y: point.y + point.ny * laneOffset };
  };
  const center = Array.from({ length: 201 }, (_, index) => sample(index / 200));
  const lengths = [0];
  for (let index = 1; index < center.length; index += 1) {
    lengths.push(lengths[index - 1] + Math.hypot(center[index].x - center[index - 1].x, center[index].y - center[index - 1].y));
  }
  const length = lengths[200];
  const cycles = Math.max(2, Math.round(length / (edge.kind === "gluon" ? 17 : 20)));
  const count = cycles * 24;
  const points = Array.from({ length: count + 1 }, (_, index) => {
    const distance = length * index / count;
    let sampleIndex = 1;
    while (sampleIndex < 200 && lengths[sampleIndex] < distance) sampleIndex += 1;
    const fraction = (distance - lengths[sampleIndex - 1]) / (lengths[sampleIndex] - lengths[sampleIndex - 1] || 1);
    const point = sample((sampleIndex - 1 + fraction) / 200);
    const phase = 2 * Math.PI * cycles * index / count;
    const taper = Math.min(1, index / 8, (count - index) / 8);
    const normal = edge.kind === "gluon"
      ? 7 * (1 - Math.cos(phase))
      : edge.kind === "photon" ? 5 * Math.sin(phase) * taper : 0;
    const along = edge.kind === "gluon" ? 6 * Math.sin(phase) : 0;
    return { x: point.x + point.nx * normal + point.tx * along, y: point.y + point.ny * normal + point.ty * along };
  });
  return { points, path: pathData(points), baseline: pathData(center), middle: sample(0.5) };
}

function connectEndpoint(points, join, tangent, atStart) {
  const endpoint = atStart ? points[0] : points.at(-1);
  const longitudinal = (join.x - endpoint.x) * tangent.tx + (join.y - endpoint.y) * tangent.ty;
  if (atStart) {
    let index = 0;
    while (longitudinal > 0 && index < points.length - 2 &&
      (points[index].x - endpoint.x) * tangent.tx + (points[index].y - endpoint.y) * tangent.ty < longitudinal) index += 1;
    return [join, ...points.slice(index)];
  }
  let index = points.length - 1;
  while (longitudinal < 0 && index > 1 &&
    (points[index].x - endpoint.x) * tangent.tx + (points[index].y - endpoint.y) * tangent.ty > longitudinal) index -= 1;
  return [...points.slice(0, index + 1), join];
}

function connectedGeometry(documentModel, edge, laneOffset) {
  const a = documentModel.vertices.find((vertex) => vertex.id === edge.from);
  const b = documentModel.vertices.find((vertex) => vertex.id === edge.to);
  if (edge.kind !== "fermion" || edge.bundle < 2 || edge.from === edge.to) return geometry(a, b, edge, laneOffset);
  const lane = bundleOffsets(edge).indexOf(laneOffset);
  const join = (vertex, t) => {
    const incident = documentModel.edges.filter((item) => item.kind === "fermion" && item.bundle === edge.bundle && item.from !== item.to &&
      (item.from === vertex.id || item.to === vertex.id));
    if (incident.length !== 2 || !incident.some((item) => item.id === edge.id)) return null;
    const other = incident.find((item) => item.id !== edge.id);
    const otherA = documentModel.vertices.find((item) => item.id === other.from);
    const otherB = documentModel.vertices.find((item) => item.id === other.to);
    const otherT = other.from === vertex.id ? 0 : 1;
    const normal = edgeSample(a, b, edge, t);
    const otherNormal = edgeSample(otherA, otherB, other, otherT);
    const aligned = (edge.from === vertex.id) !== (other.from === vertex.id);
    const otherLane = bundleOffsets(other)[aligned ? lane : edge.bundle - 1 - lane];
    const p = { x: vertex.x + normal.nx * laneOffset, y: vertex.y + normal.ny * laneOffset };
    const q = { x: vertex.x + otherNormal.nx * otherLane, y: vertex.y + otherNormal.ny * otherLane };
    const cross = normal.tx * otherNormal.ty - normal.ty * otherNormal.tx;
    if (Math.abs(cross) > 1e-6) {
      const along = ((q.x - p.x) * otherNormal.ty - (q.y - p.y) * otherNormal.tx) / cross;
      const miter = { x: p.x + normal.tx * along, y: p.y + normal.ty * along };
      if (Math.hypot(miter.x - vertex.x, miter.y - vertex.y) <=
        Math.max(8, 2 * Math.max(Math.abs(laneOffset), Math.abs(otherLane)))) return miter;
    }
    return { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 };
  };
  const result = geometry(a, b, edge, laneOffset);
  let points = result.points;
  const start = join(a, 0), end = join(b, 1);
  if (start) points = connectEndpoint(points, start, edgeSample(a, b, edge, 0), true);
  if (end) points = connectEndpoint(points, end, edgeSample(a, b, edge, 1), false);
  return { ...result, points, path: pathData(points) };
}

function momentumGeometry(a, b, edge) {
  const momentum = edge.momentum;
  const side = momentum.side === "left" ? -1 : 1;
  const sample = (t) => Math.hypot(b.x - a.x, b.y - a.y) < 0.01
    ? selfLoop(a, edge.loopSize, edge.loopAngle, t)
    : edge.circular ? circularArc(a, b, edge.curvature || 1, t) : curve(a, b, edge.curvature, t);
  const samples = Array.from({ length: 201 }, (_, i) => sample(i / 200));
  const lengths = [0];
  for (let i = 1; i < samples.length; i++) lengths.push(lengths[i - 1] + Math.hypot(samples[i].x - samples[i - 1].x, samples[i].y - samples[i - 1].y));
  const total = lengths.at(-1);
  const at = (fraction) => {
    const distance = fraction * total;
    let i = 1;
    while (i < 200 && lengths[i] < distance) i++;
    const t = (distance - lengths[i - 1]) / (lengths[i] - lengths[i - 1] || 1);
    const p = samples[i - 1], q = samples[i];
    const x = p.x + (q.x - p.x) * t, y = p.y + (q.y - p.y) * t;
    const dx = q.x - p.x, dy = q.y - p.y, size = Math.hypot(dx, dy) || 1;
    return { x: x - side * dy / size * 18, y: y + side * dx / size * 18,
      tx: dx / size, ty: dy / size, nx: -dy / size, ny: dx / size };
  };
  const count = Math.max(2, Math.ceil((momentum.end - momentum.start) * total / 5));
  const points = Array.from({ length: count + 1 }, (_, i) => at(momentum.start + (momentum.end - momentum.start) * i / count));
  const tip = momentum.direction === "forward" ? points.at(-1) : points[0], sign = momentum.direction === "forward" ? 1 : -1;
  const arrow = [{ x: tip.x, y: tip.y },
    { x: tip.x - sign * tip.tx * 12 + tip.nx * 5, y: tip.y - sign * tip.ty * 12 + tip.ny * 5 },
    { x: tip.x - sign * tip.tx * 12 - tip.nx * 5, y: tip.y - sign * tip.ty * 12 - tip.ny * 5 }];
  const middle = at((momentum.start + momentum.end) / 2);
  return { points, arrow, label: { x: middle.x + side * middle.nx * 30 + (momentum.labelX ?? 0), y: middle.y + side * middle.ny * 30 + (momentum.labelY ?? 0) } };
}

const texWords = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", zeta: "ζ", eta: "η", theta: "θ",
  lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ", phi: "φ",
  varphi: "ϕ", chi: "χ", psi: "ψ", omega: "ω", Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ",
  Pi: "Π", Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω", bar: "",
};
const superscript = { 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾" };
const subscript = { 0: "₀", 1: "₁", 2: "₂", 3: "₃", 4: "₄", 5: "₅", 6: "₆", 7: "₇", 8: "₈", 9: "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎" };

function translateScript(value, table, marker) {
  const translated = [...value].map((character) => table[character] || character).join("");
  return translated === value ? marker + value : translated;
}

function displayLabel(source) {
  return source
    .replace(/\\(?:bar|overline)\{([^{}]+)\}/g, (_, value) => value + "̄")
    .replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, (_, top, bottom) => `(${top})⁄(${bottom})`)
    .replace(/\\(?:mathrm|mathbf|mathit|text)\{([^{}]+)\}/g, "$1")
    .replace(/\\([A-Za-z]+)/g, (_, word) => texWords[word] ?? `\\${word}`)
    .replace(/\^\{([^{}]+)\}/g, (_, value) => translateScript(value, superscript, "^"))
    .replace(/_\{([^{}]+)\}/g, (_, value) => translateScript(value, subscript, "_"))
    .replace(/\^([A-Za-z0-9+\-=])/g, (_, value) => translateScript(value, superscript, "^"))
    .replace(/_([A-Za-z0-9+\-=])/g, (_, value) => translateScript(value, subscript, "_"))
    .replace(/[{}]/g, "");
}

function plainTexAtom(value) {
  return value
    .replace(/\\([A-Za-z]+)/g, (_, word) => texWords[word] ?? `\\${word}`)
    .replace(/[{}]/g, "");
}

function labelRuns(source) {
  if (!source || /\\(?:frac|mathrm|mathbf|mathit|text)\b/.test(source)) {
    return [{ text: displayLabel(source), script: 0, overbar: false }];
  }
  const token = /\\(?:bar|overline)\{((?:\\[A-Za-z]+|[^{}])+)\}|([_^])\{([^{}]+)\}|([_^])([A-Za-z0-9+\-=])|\\([A-Za-z]+)|([^{}])/g;
  const runs = [];
  for (const match of source.matchAll(token)) {
    const [, overbar, groupedScript, groupedValue, singleScript, singleValue, command, literal] = match;
    if (overbar !== undefined) runs.push({ text: plainTexAtom(overbar), script: 0, overbar: true });
    else if (groupedScript !== undefined) runs.push({ text: plainTexAtom(groupedValue), script: groupedScript === "^" ? -1 : 1, overbar: false });
    else if (singleScript !== undefined) runs.push({ text: singleValue, script: singleScript === "^" ? -1 : 1, overbar: false });
    else if (command !== undefined) runs.push({ text: texWords[command] ?? `\\${command}`, script: 0, overbar: false });
    else if (literal) runs.push({ text: literal, script: 0, overbar: false });
  }
  return runs.length ? runs : [{ text: displayLabel(source), script: 0, overbar: false }];
}

function svgLabel(source) {
  return labelRuns(source).map((run) => {
    const attributes = [
      run.script ? `baseline-shift="${run.script < 0 ? "super" : "sub"}" font-size="72%"` : "",
      run.overbar ? 'text-decoration="overline"' : "",
    ].filter(Boolean).join(" ");
    return `<tspan${attributes ? ` ${attributes}` : ""}>${escapeXml(run.text)}</tspan>`;
  }).join("");
}

function htmlLabel(source) {
  return labelRuns(source).map((run) => {
    const classes = [run.script ? `math-script ${run.script < 0 ? "sup" : "sub"}` : "", run.overbar ? "math-overbar" : ""].filter(Boolean).join(" ");
    return classes ? `<span class="${classes}">${escapeXml(run.text)}</span>` : escapeXml(run.text);
  }).join("");
}

function markerArtwork(vertex, stroke) {
  const marker = vertex.marker || (vertex.visible ? "dot" : "none");
  if (marker === "none") return "";
  if (marker === "dot") return `<circle cx="${vertex.x}" cy="${vertex.y}" r="${stroke * 1.9}" fill="#172333"/>`;
  const radius = vertex.markerSize;
  const base = `<circle cx="${vertex.x}" cy="${vertex.y}" r="${radius}" fill="${marker === "filled" ? "#172333" : "white"}"/>`;
  const outline = `<circle cx="${vertex.x}" cy="${vertex.y}" r="${radius}" fill="none" stroke="#172333" stroke-width="${stroke}"/>`;
  if (marker === "open" || marker === "filled") return base + outline;
  if (marker === "dotted") {
    const dots = [];
    for (let x = -radius + 4; x <= radius - 4; x += 7) {
      for (let y = -radius + 4; y <= radius - 4; y += 7) {
        if (x ** 2 + y ** 2 <= (radius - 3) ** 2) dots.push(`<circle cx="${vertex.x + x}" cy="${vertex.y + y}" r="1.35" fill="#172333"/>`);
      }
    }
    return base + dots.join("") + outline;
  }
  const hatch = (angle) => {
    const radians = angle * Math.PI / 180;
    const direction = { x: Math.cos(radians), y: Math.sin(radians) };
    const normal = { x: -direction.y, y: direction.x };
    const lines = [];
    for (let offset = -radius + 4; offset <= radius - 4; offset += 7) {
      const half = Math.sqrt(radius ** 2 - offset ** 2);
      const first = { x: vertex.x + normal.x * offset - direction.x * half, y: vertex.y + normal.y * offset - direction.y * half };
      const second = { x: vertex.x + normal.x * offset + direction.x * half, y: vertex.y + normal.y * offset + direction.y * half };
      lines.push(`<line x1="${first.x}" y1="${first.y}" x2="${second.x}" y2="${second.y}" stroke="#172333" stroke-width="${Math.max(1, stroke * 0.65)}"/>`);
    }
    return lines.join("");
  };
  return base + hatch(45) + (marker === "crosshatched" ? hatch(-45) : "") + outline;
}

function artwork(documentModel) {
  const unit = WIDTH / (documentModel.style.widthMm * 72 / 25.4);
  const stroke = documentModel.style.strokePt * unit;
  const font = documentModel.style.fontPt * unit;
  const paths = [];
  const labels = [];
  for (const edge of documentModel.edges) {
    const start = documentModel.vertices.find((item) => item.id === edge.from);
    const end = documentModel.vertices.find((item) => item.id === edge.to);
    if (!start || !end) continue;
    const dash = edge.kind === "scalar" ? ' stroke-dasharray="9 7"' : edge.kind === "ghost" ? ' stroke-dasharray="1 7"' : "";
    for (const offset of bundleOffsets(edge)) {
      const shape = connectedGeometry(documentModel, edge, offset);
      paths.push(`<path d="${shape.path}" fill="none" stroke="${edge.color}" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round"${dash}/>`);
      if (edge.arrow !== "none") {
        const sign = edge.arrow === "forward" ? 1 : -1;
        const size = stroke * 4.2;
        const point = shape.middle;
        const tip = { x: point.x + point.tx * size * sign, y: point.y + point.ty * size * sign };
        const left = { x: point.x - point.tx * size * 0.65 * sign + point.nx * size * 0.5, y: point.y - point.ty * size * 0.65 * sign + point.ny * size * 0.5 };
        const right = { x: point.x - point.tx * size * 0.65 * sign - point.nx * size * 0.5, y: point.y - point.ty * size * 0.65 * sign - point.ny * size * 0.5 };
        paths.push(`<path d="M${tip.x},${tip.y} L${left.x},${left.y} L${right.x},${right.y} Z" fill="${edge.color}"/>`);
      }
    }
    if (edge.label) {
      const point = geometry(start, end, edge).middle;
      const x = point.x + point.nx * edge.labelOffset + edge.labelX;
      const y = point.y + point.ny * edge.labelOffset + edge.labelY;
      labels.push(`<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" font-family="serif" font-size="${font}" fill="${edge.color}">${svgLabel(edge.label)}</text>`);
    }
    if (edge.momentum) {
      const path = momentumGeometry(start, end, edge);
      paths.push(`<polyline points="${path.points.map((p) => `${p.x},${p.y}`).join(" ")}" fill="none" stroke="${edge.momentum.color}" stroke-width="${stroke * 0.8}" stroke-linecap="round"/>`);
      paths.push(`<polygon points="${path.arrow.map((p) => `${p.x},${p.y}`).join(" ")}" fill="${edge.momentum.color}"/>`);
      if (edge.momentum.label) labels.push(`<text x="${path.label.x}" y="${path.label.y}" text-anchor="middle" dominant-baseline="central" font-family="serif" font-size="${font}" fill="${edge.momentum.color}">${svgLabel(edge.momentum.label)}</text>`);
    }
  }
  for (const item of documentModel.annotations) {
    if (item.type === "label") {
      if (item.text) labels.push(`<text x="${item.x}" y="${item.y}" text-anchor="middle" dominant-baseline="central" font-family="serif" font-size="${font}" fill="${item.color}">${svgLabel(item.text)}</text>`);
    } else {
      const dx = item.x2 - item.x1, dy = item.y2 - item.y1, size = Math.hypot(dx, dy);
      if (size < 1) continue;
      const tx = dx / size, ty = dy / size, nx = -ty, ny = tx;
      paths.push(`<line x1="${item.x1}" y1="${item.y1}" x2="${item.x2}" y2="${item.y2}" stroke="${item.color}" stroke-width="${stroke}"/>`);
      paths.push(`<polygon points="${item.x2},${item.y2} ${item.x2 - tx * 12 + nx * 5},${item.y2 - ty * 12 + ny * 5} ${item.x2 - tx * 12 - nx * 5},${item.y2 - ty * 12 - ny * 5}" fill="${item.color}"/>`);
    }
  }
  for (const vertex of documentModel.vertices) {
    paths.push(markerArtwork(vertex, stroke));
    if (vertex.label) labels.push(`<text x="${vertex.x + vertex.labelX}" y="${vertex.y + vertex.labelY}" text-anchor="middle" dominant-baseline="central" font-family="serif" font-size="${font}" fill="#172333">${svgLabel(vertex.label)}</text>`);
  }
  return paths.join("") + labels.join("");
}

function gridArtwork() {
  if (!state.showGrid) return "";
  const spacing = state.gridSize;
  const lines = [];
  for (let x = spacing; x < WIDTH; x += spacing) lines.push(`<line x1="${x}" y1="0" x2="${x}" y2="${HEIGHT}"/>`);
  for (let y = spacing; y < HEIGHT; y += spacing) lines.push(`<line x1="0" y1="${y}" x2="${WIDTH}" y2="${y}"/>`);
  return `<g stroke="#d9e0e7" stroke-width="0.7">${lines.join("")}</g>`;
}

function labelPosition(edge) {
  const start = vertexById(edge.from);
  const end = vertexById(edge.to);
  if (!start || !end) return { x: 0, y: 0 };
  const point = geometry(start, end, edge).middle;
  return {
    x: point.x + point.nx * edge.labelOffset + edge.labelX,
    y: point.y + point.ny * edge.labelOffset + edge.labelY,
  };
}

function labelLimits(source, x, y) {
  const font = state.document.style.fontPt * WIDTH / ((state.document.style.widthMm * 72) / 25.4);
  const width = Math.max(28, labelWidth(source, font));
  const halfWidth = Math.min(width / 2, WIDTH / 2);
  const halfHeight = Math.min(font * 0.8, HEIGHT / 2);
  return { minX: halfWidth - x, maxX: WIDTH - halfWidth - x,
    minY: halfHeight - y, maxY: HEIGHT - halfHeight - y };
}

const labelMeasure = document.createElement("canvas").getContext("2d");
function labelWidth(source, font) {
  return labelRuns(source).reduce((width, run) => {
    labelMeasure.font = `${font * (run.script ? 0.72 : 1)}px "FDS Serif", serif`;
    return width + labelMeasure.measureText(run.text).width;
  }, 0);
}

function momentumLabelBase(edge) {
  const point = momentumGeometry(vertexById(edge.from), vertexById(edge.to), edge).label;
  return { x: point.x - (edge.momentum.labelX ?? 0), y: point.y - (edge.momentum.labelY ?? 0) };
}

function renderCanvas() {
  const canvas = $("#diagram-canvas");
  if (!state.document) return;
  const unit = WIDTH / (state.document.style.widthMm * 72 / 25.4);
  const font = state.document.style.fontPt * unit;
  const edgeHits = [];
  const edgeSelection = [];
  const labelHits = [];
  const controls = [];
  for (const edge of state.document.edges) {
    const start = vertexById(edge.from);
    const end = vertexById(edge.to);
    if (!start || !end) continue;
    const id = escapeXml(edge.id);
    const lanes = bundleOffsets(edge).map((offset) => connectedGeometry(state.document, edge, offset));
    for (const lane of lanes) edgeHits.push(`<path class="hit hit-edge" data-kind="edge" data-id="${id}" d="${lane.path}"/>`);
    if (edge.momentum) {
      const path = momentumGeometry(start, end, edge);
      edgeHits.push(`<polyline class="hit hit-edge" data-kind="edge" data-id="${id}" points="${path.points.map((p) => `${p.x},${p.y}`).join(" ")}"/>`);
      if (edge.momentum.label) {
        const width = Math.max(28, labelWidth(edge.momentum.label, font));
        labelHits.push(`<rect class="hit hit-label" data-kind="momentum-label" data-id="${id}" x="${path.label.x - width / 2}" y="${path.label.y - font}" width="${width}" height="${font * 2}"/>`);
      }
    }
    if (state.tool === "select" && edge.id === state.selected) for (const lane of lanes) {
      const points = lane.points.map((point) => `${point.x},${point.y}`).join(" ");
      edgeSelection.push(`<polyline class="edge-selection halo" points="${points}"/><polyline class="edge-selection rim" points="${points}"/>`);
    }
    if (edge.label) {
      const position = labelPosition(edge);
      const width = Math.max(28, labelWidth(edge.label, font));
      const height = Math.max(22, font * 1.6);
      labelHits.push(`<rect class="hit hit-label" data-kind="edge-label" data-id="${id}" x="${position.x - width / 2}" y="${position.y - height / 2}" width="${width}" height="${height}"/>`);
    }
  }
  for (const item of state.document.annotations) {
    const id = escapeXml(item.id);
    if (item.type === "label") {
      const width = Math.max(28, labelWidth(item.text, font));
      const height = Math.max(22, font * 1.6);
      labelHits.push(`<rect class="hit hit-label" data-kind="annotation-label" data-id="${id}" x="${item.x - width / 2}" y="${item.y - height / 2}" width="${width}" height="${height}"/>`);
    } else edgeHits.push(`<line class="hit hit-edge" data-kind="annotation-arrow" data-id="${id}" x1="${item.x1}" y1="${item.y1}" x2="${item.x2}" y2="${item.y2}"/>`);
    if (state.tool === "select" && state.selected === item.id)
      controls.push(`<circle class="handle selected" cx="${item.type === "label" ? item.x : (item.x1 + item.x2) / 2}" cy="${item.type === "label" ? item.y : (item.y1 + item.y2) / 2}" r="5"/>`);
  }
  for (const vertex of state.document.vertices) {
    const id = escapeXml(vertex.id);
    if (vertex.label) {
      const x = vertex.x + vertex.labelX;
      const y = vertex.y + vertex.labelY;
      const width = Math.max(28, labelWidth(vertex.label, font));
      const height = Math.max(22, font * 1.6);
      labelHits.push(`<rect class="hit hit-label" data-kind="vertex-label" data-id="${id}" x="${x - width / 2}" y="${y - height / 2}" width="${width}" height="${height}"/>`);
    }
    const classes = ["handle", "hit", "hit-vertex"];
    if (state.tool === "select" && vertex.id === state.selected) classes.push("selected");
    if (vertex.id === state.connectionStart) classes.push("connecting");
    controls.push(`<circle class="${classes.join(" ")}" data-kind="vertex" data-id="${id}" cx="${vertex.x}" cy="${vertex.y}" r="${(state.tool === "select" && vertex.id === state.selected) || vertex.id === state.connectionStart ? 7 : 4}"/>`);
  }
  canvas.innerHTML = `${gridArtwork()}<g aria-hidden="true">${edgeSelection.join("")}${artwork(state.document)}</g>${edgeHits.join("")}${labelHits.join("")}${controls.join("")}`;
}

function setStatus(message) {
  $("#status").textContent = message;
}

let toastTimer = null;
function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 4200);
}

function showMessage(title, body) {
  $("#message-title").textContent = title;
  $("#message-body").textContent = body;
  $("#message-dialog").showModal();
}

function scheduleAutosave() {
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(() => {
    if (persistProject()) setStatus("Saved in this browser");
  }, 500);
}

function persistProject() {
  if (!state.document) return false;
  const active = state.projects.find((project) => project.id === state.activeProjectId);
  if (active) active.diagram = clone(state.document);
  try {
    localStorage.setItem(PROJECTS_STORE, JSON.stringify({ activeId: state.activeProjectId, projects: state.projects }));
    localStorage.setItem(STORE, JSON.stringify(state.document));
    return true;
  } catch (_error) {
    notify("Browser storage is unavailable. Use Save to keep a project file.");
    return false;
  }
}

function sidebarWidth(side) {
  return Math.round($(side === "library" ? ".library" : ".inspector").getBoundingClientRect().width);
}

function setSidebarWidth(side, requestedWidth) {
  const workspace = $(".workspace");
  const other = side === "library" ? "inspector" : "library";
  const minimum = side === "library" ? 170 : 220;
  const maximum = Math.max(minimum, Math.min(440, workspace.clientWidth - sidebarWidth(other) - 352));
  const width = clamp(Math.round(requestedWidth), minimum, maximum);
  state[`${side}Width`] = width;
  workspace.style.setProperty(`--${side}-width`, `${width}px`);
  const handle = $(`.${side}-resizer`);
  handle.setAttribute("aria-valuemin", String(minimum));
  handle.setAttribute("aria-valuemax", String(maximum));
  handle.setAttribute("aria-valuenow", String(width));
  handle.setAttribute("aria-valuetext", `${width} pixels`);
}

function applySidebarWidths() {
  const workspace = $(".workspace");
  for (const side of ["library", "inspector"]) {
    const width = state[`${side}Width`];
    if (Number.isFinite(width)) workspace.style.setProperty(`--${side}-width`, `${width}px`);
    else workspace.style.removeProperty(`--${side}-width`);
  }
  if (window.matchMedia("(min-width: 781px)").matches) {
    if (Number.isFinite(state.libraryWidth)) setSidebarWidth("library", state.libraryWidth);
    if (Number.isFinite(state.inspectorWidth)) setSidebarWidth("inspector", state.inspectorWidth);
  }
  for (const side of ["library", "inspector"]) {
    const width = sidebarWidth(side);
    $(`.${side}-resizer`).setAttribute("aria-valuenow", String(width));
    $(`.${side}-resizer`).setAttribute("aria-valuetext", `${width} pixels`);
  }
}

function beginSidebarResize(event) {
  if (event.button !== 0 || !window.matchMedia("(min-width: 781px)").matches) return;
  const side = event.currentTarget.classList.contains("library-resizer") ? "library" : "inspector";
  state.sidebarDrag = { side, startX: event.clientX, startWidth: sidebarWidth(side) };
  event.currentTarget.setPointerCapture(event.pointerId);
  document.body.classList.add("resizing-sidebar");
  event.preventDefault();
}

function moveSidebarResize(event) {
  if (!state.sidebarDrag || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
  const { side, startX, startWidth } = state.sidebarDrag;
  const delta = event.clientX - startX;
  setSidebarWidth(side, startWidth + (side === "library" ? delta : -delta));
}

function endSidebarResize(event) {
  if (!state.sidebarDrag) return;
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  const side = state.sidebarDrag.side;
  state.sidebarDrag = null;
  document.body.classList.remove("resizing-sidebar");
  persistSettings();
  setStatus(`${titleCase(side)} width: ${sidebarWidth(side)} px`);
}

function resizeSidebarWithKeyboard(event) {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key) || !window.matchMedia("(min-width: 781px)").matches) return;
  const side = event.currentTarget.classList.contains("library-resizer") ? "library" : "inspector";
  const direction = event.key === "ArrowRight" ? 1 : -1;
  setSidebarWidth(side, sidebarWidth(side) + direction * (side === "library" ? 20 : -20));
  persistSettings();
  event.preventDefault();
}

function persistSettings() {
  try {
    localStorage.setItem(SETTINGS_STORE, JSON.stringify({
      snap: state.snap, showGrid: state.showGrid, showFigurePanel: state.showFigurePanel, gridSize: state.gridSize, theme: state.theme,
      libraryWidth: state.libraryWidth, inspectorWidth: state.inspectorWidth,
    }));
  } catch (_error) {
    // Editor settings can safely remain session-only.
  }
}

function record(before, message = "Modified") {
  if (JSON.stringify(before) === JSON.stringify(state.document)) return;
  state.past.push(before);
  if (state.past.length > 60) state.past.shift();
  state.future = [];
  setStatus(message);
  renderAll();
  scheduleAutosave();
}

function commit(change, message = "Modified") {
  const before = clone(state.document);
  change(state.document);
  record(before, message);
}

function replaceDocument(documentModel, message, projectId = null) {
  clearTimeout(state.autosaveTimer);
  if (state.document) persistProject();
  if (projectId) state.activeProjectId = projectId;
  else {
    state.activeProjectId = uuid();
    state.projects.unshift({ id: state.activeProjectId, diagram: clone(documentModel) });
  }
  state.document = clone(documentModel);
  state.past = [];
  state.future = [];
  state.selected = null;
  state.connectionStart = null;
  state.tool = "select";
  setStatus(message);
  renderAll();
  persistProject();
}

function deleteProject(id) {
  if (!state.projects.some((item) => item.id === id)) return;
  clearTimeout(state.autosaveTimer);
  const active = state.projects.find((item) => item.id === state.activeProjectId);
  if (active) active.diagram = clone(state.document);
  state.projects = state.projects.filter((item) => item.id !== id);
  if (id === state.activeProjectId) {
    state.document = null;
    const next = state.projects[0];
    replaceDocument(next?.diagram || blankDiagram(), "Diagram deleted", next?.id || null);
  } else {
    persistProject();
    renderLists();
    setStatus("Diagram deleted");
  }
}

function undo() {
  if (!state.past.length) return;
  state.future.unshift(clone(state.document));
  state.document = state.past.pop();
  state.selected = null;
  state.connectionStart = null;
  setStatus("Undone");
  renderAll();
  scheduleAutosave();
}

function redo() {
  if (!state.future.length) return;
  state.past.push(clone(state.document));
  state.document = state.future.shift();
  state.selected = null;
  state.connectionStart = null;
  setStatus("Redone");
  renderAll();
  scheduleAutosave();
}

function removeSelected() {
  if (!state.selected) return;
  const objectId = state.selected;
  commit((documentModel) => {
    documentModel.vertices = documentModel.vertices.filter((item) => item.id !== objectId);
    documentModel.edges = documentModel.edges.filter((item) => item.id !== objectId && item.from !== objectId && item.to !== objectId);
    documentModel.annotations = documentModel.annotations.filter((item) => item.id !== objectId);
  }, "Object deleted");
  state.selected = null;
  state.connectionStart = null;
  renderAll();
}

function snapCoordinate(value, minimum, maximum) {
  const spacing = state.gridSize;
  const snapped = Math.floor(value / spacing + 0.5) * spacing;
  return clamp(snapped, Math.ceil(minimum / spacing) * spacing, Math.floor(maximum / spacing) * spacing);
}

function setSnap(enabled) {
  state.snap = enabled;
  persistSettings();
  if (enabled) {
    commit((documentModel) => {
      for (const vertex of documentModel.vertices) {
        vertex.x = snapCoordinate(vertex.x, 20, 700);
        vertex.y = snapCoordinate(vertex.y, 20, 460);
      }
    }, "Vertices aligned to grid");
  } else {
    setStatus("Grid snapping off");
    renderAll();
  }
}

function setTool(tool) {
  state.tool = tool;
  state.selected = null;
  state.connectionStart = null;
  state.drag = null;
  setStatus(`${titleCase(tool === "vertex" ? "add vertex" : tool)} tool`);
  renderAll();
}

function hintText() {
  if (state.tool === "vertex") return "Click the page to place a vertex.";
  if (state.tool === "label") return "Click the page to place a free label.";
  if (state.tool === "arrow") return "Drag on the page to draw a free arrow.";
  if (state.tool === "connect") return state.connectionStart ? "Choose the second vertex." : "Choose two vertices to connect, in the direction of particle flow.";
  if (state.tool === "loop") {
    if (state.loopMode === "single") return "Choose one vertex to attach a loop.";
    return state.connectionStart ? "Choose the second vertex to complete the loop." : "Choose two vertices for the loop.";
  }
  return "Drag vertices or their labels. Select a propagator to customize it.";
}

function renderLists() {
  $("#projects").innerHTML = state.projects.map((project) => {
    const title = escapeXml(project.id === state.activeProjectId ? state.document.title : project.diagram.title);
    return `<div class="project-row" role="listitem"><button type="button" data-project="${escapeXml(project.id)}" aria-current="${project.id === state.activeProjectId}" title="Open ${title}">${title}</button><button type="button" class="project-delete" data-delete-project="${escapeXml(project.id)}" aria-label="Delete ${title}" title="Delete ${title}">×</button></div>`;
  }).join("");
  const objects = [];
  state.document.vertices.forEach((vertex, index) => {
    objects.push(`<button type="button" role="option" data-object="${escapeXml(vertex.id)}" aria-selected="${vertex.id === state.selected}" title="Vertex ${index + 1}${vertex.label ? ` · ${escapeXml(displayLabel(vertex.label))}` : ""}">Vertex ${index + 1}${vertex.label ? ` · ${htmlLabel(vertex.label)}` : ""}</button>`);
  });
  state.document.edges.forEach((edge, index) => {
    objects.push(`<button type="button" role="option" data-object="${escapeXml(edge.id)}" aria-selected="${edge.id === state.selected}">${titleCase(edge.kind)} ${index + 1}</button>`);
  });
  state.document.annotations.forEach((item, index) => {
    objects.push(`<button type="button" role="option" data-object="${escapeXml(item.id)}" aria-selected="${item.id === state.selected}">${item.type === "label" ? `Label ${index + 1} · ${htmlLabel(item.text)}` : `Arrow ${index + 1}`}</button>`);
  });
  $("#objects").innerHTML = objects.join("") || '<p class="muted empty-note">No objects yet</p>';
}

function field(label, path, value, options = {}) {
  const attributes = [
    `data-path="${escapeXml(path)}"`,
    options.type === "number" ? 'type="number"' : 'type="text"',
    options.min !== undefined ? `min="${options.min}"` : "",
    options.max !== undefined ? `max="${options.max}"` : "",
    options.step !== undefined ? `step="${options.step}"` : "",
    options.maxlength ? `maxlength="${options.maxlength}"` : "",
  ].filter(Boolean).join(" ");
  return `<label class="field">${escapeXml(label)}<input ${attributes} value="${escapeXml(value)}"></label>`;
}

function choice(label, path, value, options) {
  return `<label class="field">${escapeXml(label)}<select data-path="${escapeXml(path)}">${options.map((option) => {
    const item = typeof option === "string" ? { value: option, label: titleCase(option) } : option;
    return `<option value="${escapeXml(item.value)}"${item.value === value ? " selected" : ""}>${escapeXml(item.label)}</option>`;
  }).join("")}</select></label>`;
}

function renderInspector() {
  const inspector = $(".selection-section");
  const context = `${state.tool}:${state.selected || ""}`;
  const fineOpen = inspector.dataset.objectId === context && inspector.querySelector("details")?.open;
  const scrollTop = inspector.dataset.objectId === context ? inspector.scrollTop : 0;
  const documentModel = state.document;
  let html = "";
  const vertex = vertexById(state.selected);
  const edge = edgeById(state.selected);
  const annotation = annotationById(state.selected);
  if (vertex) {
    html += '<h3>Vertex</h3>';
    html += field("Label (TeX)", "vertex.label", vertex.label, { maxlength: 200 });
    html += field("X position", "vertex.x", niceNumber(vertex.x), { type: "number", min: 20, max: 700, step: 1 });
    html += field("Y position", "vertex.y", niceNumber(vertex.y), { type: "number", min: 20, max: 460, step: 1 });
    const limits = labelLimits(vertex.label, vertex.x, vertex.y);
    html += field("Label X", "vertex.labelX", niceNumber(vertex.labelX), { type: "number", min: Math.ceil(limits.minX), max: Math.floor(limits.maxX), step: 1 });
    html += field("Label Y", "vertex.labelY", niceNumber(vertex.labelY), { type: "number", min: Math.ceil(limits.minY), max: Math.floor(limits.maxY), step: 1 });
    html += choice("Vertex style", "vertex.marker", vertex.marker, MARKERS);
    if (!['none', 'dot'].includes(vertex.marker)) html += field("Circle radius", "vertex.markerSize", niceNumber(vertex.markerSize), { type: "number", min: 6, max: 60, step: 1 });
    html += '<button type="button" class="danger" data-action="delete">Delete vertex</button>';
  } else if (edge) {
    html += '<h3>Propagator</h3>';
    html += choice("Particle style", "edge.kind", edge.kind, KINDS);
    html += field("Label (TeX)", "edge.label", edge.label, { maxlength: 200 });
    html += choice("Arrow direction", "edge.arrow", edge.arrow, [{ value: "forward", label: "Start → end" }, { value: "reverse", label: "End → start" }, { value: "none", label: "No arrow" }]);
    if (edge.kind === "fermion" && edge.from !== edge.to) {
      html += choice("Quark bundle", "edge.bundle", String(edge.bundle), ["1", "2", "3"]);
      if (edge.bundle > 1) html += field("Quark spacing", "edge.bundleSpacing", niceNumber(edge.bundleSpacing), { type: "number", min: 4, max: 40, step: 1 });
    }
    if (edge.from === edge.to) {
      html += field("Loop size", "edge.loopSize", niceNumber(edge.loopSize), { type: "number", min: 30, max: 180, step: 1 });
      html += field("Loop angle", "edge.loopAngle", niceNumber(edge.loopAngle), { type: "number", min: -180, max: 180, step: 1 });
    } else if (!edge.circular) {
      html += field("Curvature", "edge.curvature", niceNumber(edge.curvature), { type: "number", min: -220, max: 220, step: 1 });
    }
    html += field("Label offset", "edge.labelOffset", niceNumber(edge.labelOffset), { type: "number", min: -120, max: 120, step: 1 });
    html += field("Label X", "edge.labelX", niceNumber(edge.labelX), { type: "number", min: -150, max: 150, step: 1 });
    html += field("Label Y", "edge.labelY", niceNumber(edge.labelY), { type: "number", min: -150, max: 150, step: 1 });
    html += `<label class="field">Line color<input data-path="edge.color" type="color" value="${escapeXml(edge.color)}"></label>`;
    html += `<label class="check"><input data-path="edge.momentumEnabled" type="checkbox"${edge.momentum ? " checked" : ""}> Momentum arrow</label>`;
    if (edge.momentum) {
      html += field("Momentum label (TeX)", "momentum.label", edge.momentum.label, { maxlength: 200 });
      const base = momentumLabelBase(edge);
      const limits = labelLimits(edge.momentum.label, base.x, base.y);
      html += field("Momentum label X", "momentum.labelX", niceNumber(edge.momentum.labelX ?? 0), { type: "number", min: Math.ceil(limits.minX), max: Math.floor(limits.maxX), step: 1 });
      html += field("Momentum label Y", "momentum.labelY", niceNumber(edge.momentum.labelY ?? 0), { type: "number", min: Math.ceil(limits.minY), max: Math.floor(limits.maxY), step: 1 });
      html += choice("Momentum direction", "momentum.direction", edge.momentum.direction, [
        { value: "forward", label: "Start → end" }, { value: "reverse", label: "End → start" },
      ]);
      html += choice("Momentum side", "momentum.side", edge.momentum.side, ["left", "right"]);
      html += `<details><summary>Fine placement</summary>`;
      html += field("Start (%)", "momentum.start", niceNumber(edge.momentum.start * 100), { type: "number", min: 0, max: 95, step: 1 });
      html += field("End (%)", "momentum.end", niceNumber(edge.momentum.end * 100), { type: "number", min: 5, max: 100, step: 1 });
      html += `<label class="field">Arrow color<input data-path="momentum.color" type="color" value="${escapeXml(edge.momentum.color)}"></label></details>`;
    }
    html += '<button type="button" class="danger" data-action="delete">Delete propagator</button>';
  } else if (annotation) {
    html += `<h3>${annotation.type === "label" ? "Free label" : "Free arrow"}</h3>`;
    if (annotation.type === "label") {
      html += field("Label (TeX)", "annotation.text", annotation.text, { maxlength: 200 });
      html += field("X position", "annotation.x", niceNumber(annotation.x), { type: "number", min: 0, max: 720, step: 1 });
      html += field("Y position", "annotation.y", niceNumber(annotation.y), { type: "number", min: 0, max: 480, step: 1 });
    } else for (const coordinate of ["x1", "y1", "x2", "y2"])
      html += field(coordinate.toUpperCase(), `annotation.${coordinate}`, niceNumber(annotation[coordinate]), { type: "number", min: 0, max: coordinate.startsWith("x") ? 720 : 480, step: 1 });
    html += `<label class="field">Color<input data-path="annotation.color" type="color" value="${escapeXml(annotation.color)}"></label>`;
    html += '<button type="button" class="danger" data-action="delete">Delete annotation</button>';
  }
  if (state.tool !== "select") {
    html = `<p class="tool-note">${escapeXml(hintText())}</p>`;
    if (state.tool === "vertex") {
      html += choice("Vertex icon style", "setting.newMarker", state.newMarker, MARKERS);
      if (!["none", "dot"].includes(state.newMarker)) html += field("Icon radius", "setting.newMarkerSize", state.newMarkerSize, { type: "number", min: 6, max: 60, step: 1 });
    }
    if (state.tool === "connect" || state.tool === "loop") {
      html += choice("Line type", "setting.newKind", state.newKind, KINDS);
      if (state.tool === "connect") html += choice("Arrow direction", "setting.newArrow", state.newArrow, [
        { value: "auto", label: "Automatic" }, { value: "forward", label: "Start → end" }, { value: "reverse", label: "End → start" }, { value: "none", label: "No arrow" },
      ]);
      if (state.tool === "loop") html += choice("Loop type", "setting.loopMode", state.loopMode, [{ value: "single", label: "Single vertex" }, { value: "double", label: "Two vertices" }]);
    }
  }
  if (state.tool === "select" && !html) html = '<p class="tool-note">Click a vertex or propagator on the page, or choose one from Objects, to edit it. Drag vertices and labels to move them.</p>';
  inspector.querySelector("h2").textContent = { select: "Selection", vertex: "Add vertex", connect: "Connect vertices", loop: "Add loop", label: "Add free label", arrow: "Add free arrow" }[state.tool];
  $("#selection-details").innerHTML = html;
  inspector.dataset.objectId = context;
  inspector.scrollTop = scrollTop;
  let figure = field("Figure width (mm)", "style.widthMm", niceNumber(documentModel.style.widthMm), { type: "number", min: 60, max: 240, step: 1 });
  figure += field("Line width (pt)", "style.strokePt", niceNumber(documentModel.style.strokePt), { type: "number", min: 0.3, max: 2, step: 0.1 });
  figure += field("Text size (pt)", "style.fontPt", niceNumber(documentModel.style.fontPt), { type: "number", min: 5, max: 18, step: 1 });
  figure += `<label class="check"><input data-setting="snap" type="checkbox"${state.snap ? " checked" : ""}> Snap to grid</label>`;
  figure += `<label class="check"><input data-setting="showGrid" type="checkbox"${state.showGrid ? " checked" : ""}> Show page grid</label>`;
  $("#figure-details").innerHTML = figure;
  $(".figure-section").hidden = !state.showFigurePanel;
  const fine = inspector.querySelector("details");
  if (fine) fine.open = fineOpen;
}

function renderAll() {
  if (!state.document) return;
  renderCanvas();
  renderLists();
  renderInspector();
  $("#diagram-title").textContent = state.document.title;
  $("#object-count").textContent = `${state.document.vertices.length} vertices · ${state.document.edges.length} propagators · ${state.document.annotations.length} annotations`;
  $("#hint").textContent = hintText();
  $("#undo").disabled = state.past.length === 0;
  $("#redo").disabled = state.future.length === 0;
  $$('[data-tool]').forEach((button) => button.classList.toggle("active", button.dataset.tool === state.tool));
  $("#menu-snap").checked = state.snap;
  $("#menu-grid").checked = state.showGrid;
  $("#menu-figure-panel").checked = state.showFigurePanel;
  $("#menu-grid-size").value = String(state.gridSize);
  $("#menu-theme").value = state.theme;
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-FDS-Token": state.token },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const result = await response.json();
      if (result.error) message = result.error;
    } catch (_error) {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return response;
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function fileName(title) {
  return title.replace(/[^a-zA-Z0-9-]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "diagram";
}

function saveProject() {
  const source = JSON.stringify(state.document, null, 2);
  download(new Blob([source], { type: "application/json" }), `${fileName(state.document.title)}.feynman.json`);
  setStatus("Project saved");
}

async function openProject(file) {
  if (file.size > 1_000_000) throw new Error("Project files must be smaller than 1 MB.");
  let candidate;
  try {
    candidate = JSON.parse(await file.text());
  } catch (_error) {
    throw new Error("The project is not valid JSON.");
  }
  const response = await api("/api/validate", { diagram: candidate });
  const result = await response.json();
  replaceDocument(result.diagram, "Project opened");
}

function blankDiagram() {
  return {
    version: 2,
    title: "Untitled diagram",
    vertices: [],
    edges: [],
    annotations: [],
    style: { widthMm: 120, strokePt: 0.8, fontPt: 10 },
  };
}

function openRenameDialog(projectId = state.activeProjectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  const dialog = $("#rename-dialog");
  dialog.dataset.projectId = projectId;
  const input = $("#rename-input");
  input.value = projectId === state.activeProjectId ? state.document.title : project.diagram.title;
  dialog.showModal();
  requestAnimationFrame(() => { input.focus(); input.select(); });
}

function openFigureStyleDialog() {
  const style = state.document.style;
  $("#figure-width").value = niceNumber(style.widthMm);
  $("#figure-stroke").value = niceNumber(style.strokePt);
  $("#figure-font").value = niceNumber(style.fontPt);
  $("#figure-snap").checked = state.snap;
  $("#figure-grid").checked = state.showGrid;
  $("#figure-style-dialog").showModal();
}

function updateExportOptions() {
  const format = $("#export-format").value;
  $("#export-ppi").disabled = ["svg", "pdf"].includes(format);
  $("#export-transparent").disabled = !["svg", "png"].includes(format);
  if (!["svg", "png"].includes(format)) $("#export-transparent").checked = false;
}

async function exportDiagram() {
  const button = $("#export-submit");
  button.disabled = true;
  button.textContent = "Exporting…";
  try {
    const format = $("#export-format").value;
    const response = await api("/api/export", {
      diagram: state.document,
      format,
      ppi: Number($("#export-ppi").value),
      transparent: $("#export-transparent").checked,
    });
    download(await response.blob(), `${fileName(state.document.title)}.${format}`);
    $("#export-dialog").close();
    setStatus(`${format.toUpperCase()} exported`);
  } catch (error) {
    notify(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Export";
  }
}

async function refreshLatex() {
  const area = $("#latex-source");
  const format = $("#latex-format").value;
  const reasons = unsupportedFeatures(state.document, format);
  const blocked = state.latexFormats.flatMap((item) => {
    const issues = unsupportedFeatures(state.document, item.value);
    return issues.length ? [`${item.label}: ${issues.join("; ")}`] : [];
  });
  $("#latex-compat").textContent = blocked.length ? `Unavailable for this diagram: ${blocked.join(" · ")}` : "All six formats are available for this diagram.";
  $("#copy-latex").disabled = reasons.length > 0;
  $("#copy-standalone").disabled = reasons.length > 0;
  if (reasons.length) {
    area.value = "";
    state.latexSource = "";
    state.standaloneSource = "";
    return;
  }
  area.value = "Generating source…";
  try {
    const response = await api("/api/latex", { diagram: state.document, format });
    const result = await response.json();
    state.latexSource = result.source;
    state.standaloneSource = result.standalone;
    area.value = result.source;
  } catch (error) {
    area.value = "";
    notify(error.message);
  }
}

async function openLatexDialog() {
  const formatSelect = $("#latex-format");
  for (const option of formatSelect.options) {
    const reasons = unsupportedFeatures(state.document, option.value);
    option.disabled = reasons.length > 0;
    option.title = reasons.join("; ");
  }
  if (formatSelect.selectedOptions[0]?.disabled) formatSelect.value = [...formatSelect.options].find((option) => !option.disabled)?.value || "tikz-feynman";
  $("#latex-dialog").showModal();
  await refreshLatex();
}

async function copyText(value, message) {
  try {
    await navigator.clipboard.writeText(value);
  } catch (_error) {
    const area = $("#latex-source");
    const original = area.value;
    area.value = value;
    area.select();
    document.execCommand("copy");
    area.value = original;
  }
  setStatus(message);
}

async function stopServer() {
  if (!window.confirm("Stop the local Feynman Diagram Studio Web server?")) return;
  try {
    await api("/api/shutdown", {});
    showMessage("Web app stopped", "The local server has stopped. You can close this browser tab.");
    setStatus("Web app stopped");
  } catch (error) {
    notify(error.message);
  }
}

function closeMenus() {
  $$("details.menu").forEach((details) => { details.open = false; });
}

function runAction(action) {
  closeMenus();
  if (action === "new") replaceDocument(blankDiagram(), "New blank diagram");
  else if (action === "open") $("#project-file").click();
  else if (action === "save") saveProject();
  else if (action === "undo") undo();
  else if (action === "redo") redo();
  else if (action === "delete") removeSelected();
  else if (action === "rename") openRenameDialog();
  else if (action === "figure-style") openFigureStyleDialog();
  else if (action === "export") { updateExportOptions(); $("#export-dialog").showModal(); }
  else if (action === "latex") openLatexDialog();
  else if (action === "shutdown") stopServer();
  else if (action === "shortcuts") showMessage("Keyboard shortcuts", "V  Select\nA  Add vertex\nC  Connect vertices\nL  Add loop\n\nCtrl/Cmd+Z  Undo\nCtrl/Cmd+Shift+Z  Redo\nDelete  Delete selection\nArrow keys  Nudge selected vertex\nShift+arrow keys  Nudge farther");
  else if (action === "about") showMessage("About", `Feynman Diagram Studio Web\nVersion ${state.version}\n\nLocal-first browser edition. Open source under the MIT License.`);
}

function canvasPoint(event) {
  const bounds = $("#diagram-canvas").getBoundingClientRect();
  return {
    x: (event.clientX - bounds.left) * WIDTH / bounds.width,
    y: (event.clientY - bounds.top) * HEIGHT / bounds.height,
  };
}

function beginConnection(vertex) {
  if (!state.connectionStart) {
    state.connectionStart = vertex.id;
    renderAll();
    return;
  }
  if (state.connectionStart === vertex.id) {
    setStatus("Choose a different endpoint, or use the Loop tool.");
    return;
  }
  if (state.document.edges.length >= 300) {
    notify("A project may contain at most 300 propagators.");
    return;
  }
  const newEdge = makeEdge(state.connectionStart, vertex.id, state.newKind);
  if (state.newArrow !== "auto") newEdge.arrow = state.newArrow;
  const before = clone(state.document);
  state.document.edges.push(newEdge);
  state.connectionStart = null;
  record(before, "Propagator added");
}

function beginLoop(vertex) {
  if (state.loopMode === "single") {
    if (state.document.edges.length >= 300) {
      notify("A project may contain at most 300 propagators.");
      return;
    }
    const newEdge = makeEdge(vertex.id, vertex.id, state.newKind);
    const spaces = [[0, 700 - vertex.x], [90, 460 - vertex.y], [180, vertex.x - 20], [-90, vertex.y - 20]];
    newEdge.loopAngle = spaces.sort((a, b) => b[1] - a[1])[0][0];
    const before = clone(state.document);
    state.document.edges.push(newEdge);
    record(before, "Loop added");
    return;
  }
  if (!state.connectionStart) {
    state.connectionStart = vertex.id;
    renderAll();
    return;
  }
  if (state.connectionStart === vertex.id) {
    setStatus("Choose a different vertex for a two-vertex loop.");
    return;
  }
  if (state.document.edges.length > 298) {
    notify("A project may contain at most 300 propagators.");
    return;
  }
  const start = vertexById(state.connectionStart);
  if (!start) return;
  const bend = clamp(Math.hypot(vertex.x - start.x, vertex.y - start.y) * 0.32, 70, 180);
  const first = makeEdge(start.id, vertex.id, state.newKind, "", bend);
  const second = makeEdge(start.id, vertex.id, state.newKind, "", -bend);
  first.circular = true;
  second.circular = true;
  if (state.newKind === "fermion") second.arrow = "reverse";
  const before = clone(state.document);
  state.document.edges.push(first, second);
  state.connectionStart = null;
  record(before, "Two-vertex loop added");
}

function canvasDown(event) {
  if (event.button !== 0) return;
  const point = canvasPoint(event);
  const target = event.target.closest("[data-kind]");
  const kind = target?.dataset.kind || null;
  const id = target?.dataset.id || null;
  if (state.tool === "label" || state.tool === "arrow") {
    if (state.document.annotations.length >= 300) { notify("A project may contain at most 300 annotations."); return; }
    const item = makeAnnotation(state.tool, clamp(point.x, 20, 700), clamp(point.y, 20, 460));
    const before = clone(state.document);
    state.document.annotations.push(item);
    state.selected = item.id;
    if (item.type === "arrow") {
      item.x2 = item.x1;
      item.y2 = item.y1;
      state.drag = { kind: "new-arrow", id: item.id, before, origin: point, changed: true };
      $("#diagram-canvas").setPointerCapture(event.pointerId);
      renderAll();
    } else {
      state.tool = "select";
      record(before, "Label added");
    }
    return;
  }
  if (state.tool === "vertex") {
    if (state.document.vertices.length >= 150) {
      notify("A project may contain at most 150 vertices.");
      return;
    }
    const x = state.snap ? snapCoordinate(point.x, 20, 700) : clamp(point.x, 20, 700);
    const y = state.snap ? snapCoordinate(point.y, 20, 460) : clamp(point.y, 20, 460);
    const newVertex = makeVertex(x, y);
    newVertex.marker = state.newMarker;
    newVertex.visible = state.newMarker !== "none";
    newVertex.markerSize = state.newMarkerSize;
    const before = clone(state.document);
    state.document.vertices.push(newVertex);
    state.tool = "select";
    state.selected = newVertex.id;
    record(before, "Vertex added");
    return;
  }
  const vertex = kind === "vertex" ? vertexById(id) : null;
  if (state.tool === "connect" && vertex) { beginConnection(vertex); return; }
  if (state.tool === "loop" && vertex) { beginLoop(vertex); return; }
  if (state.tool !== "select") return;
  if (!id) {
    state.selected = null;
    state.drag = null;
    renderAll();
    return;
  }
  state.selected = id;
  state.drag = {
    kind,
    id,
    before: clone(state.document),
    origin: point,
    offset: vertex ? { x: vertex.x - point.x, y: vertex.y - point.y } : { x: 0, y: 0 },
    changed: false,
  };
  $("#diagram-canvas").setPointerCapture(event.pointerId);
  renderAll();
}

function canvasMove(event) {
  const drag = state.drag;
  if (!drag || !$("#diagram-canvas").hasPointerCapture(event.pointerId)) return;
  const point = canvasPoint(event);
  const dx = point.x - drag.origin.x;
  const dy = point.y - drag.origin.y;
  if (drag.kind === "vertex") {
    const vertex = vertexById(drag.id);
    if (vertex) {
      let x = point.x + drag.offset.x;
      let y = point.y + drag.offset.y;
      if (state.snap) {
        x = snapCoordinate(x, 20, 700);
        y = snapCoordinate(y, 20, 460);
      }
      vertex.x = clamp(x, 20, 700);
      vertex.y = clamp(y, 20, 460);
    }
  } else if (drag.kind === "vertex-label") {
    const vertex = vertexById(drag.id);
    if (vertex) {
      const limits = labelLimits(vertex.label, vertex.x, vertex.y);
      vertex.labelX = clamp(vertex.labelX + dx, limits.minX, limits.maxX);
      vertex.labelY = clamp(vertex.labelY + dy, limits.minY, limits.maxY);
    }
  } else if (drag.kind === "momentum-label") {
    const edge = edgeById(drag.id);
    if (edge?.momentum) {
      const base = momentumLabelBase(edge);
      const limits = labelLimits(edge.momentum.label, base.x, base.y);
      edge.momentum.labelX = clamp((edge.momentum.labelX ?? 0) + dx, limits.minX, limits.maxX);
      edge.momentum.labelY = clamp((edge.momentum.labelY ?? 0) + dy, limits.minY, limits.maxY);
    }
  } else if (drag.kind === "edge-label") {
    const edge = edgeById(drag.id);
    if (edge) {
      edge.labelX = clamp(edge.labelX + dx, -150, 150);
      edge.labelY = clamp(edge.labelY + dy, -150, 150);
    }
  } else if (drag.kind === "annotation-label") {
    const item = annotationById(drag.id);
    if (item) { item.x = clamp(item.x + dx, 20, 700); item.y = clamp(item.y + dy, 20, 460); }
  } else if (drag.kind === "annotation-arrow") {
    const item = annotationById(drag.id);
    if (item) {
      item.x1 = clamp(item.x1 + dx, 20, 700); item.y1 = clamp(item.y1 + dy, 20, 460);
      item.x2 = clamp(item.x2 + dx, 20, 700); item.y2 = clamp(item.y2 + dy, 20, 460);
    }
  } else if (drag.kind === "new-arrow") {
    const item = annotationById(drag.id);
    if (item) { item.x2 = clamp(point.x, 20, 700); item.y2 = clamp(point.y, 20, 460); }
  }
  drag.origin = point;
  drag.changed = true;
  renderCanvas();
}

function canvasUp(event) {
  const drag = state.drag;
  if (!drag) return;
  if ($("#diagram-canvas").hasPointerCapture(event.pointerId)) $("#diagram-canvas").releasePointerCapture(event.pointerId);
  state.drag = null;
  if (drag.kind === "new-arrow") state.tool = "select";
  if (drag.changed) record(drag.before, "Object moved");
}

function inspectorChanged(input) {
  const setting = input.dataset.setting;
  if (setting === "snap") { setSnap(input.checked); return; }
  if (setting === "showGrid") {
    state.showGrid = input.checked;
    persistSettings();
    setStatus(state.showGrid ? "Page grid shown" : "Page grid hidden");
    renderAll();
    return;
  }
  const path = input.dataset.path;
  if (!path) return;
  if (path === "setting.newKind") {
    state.newKind = input.value;
    setStatus(`New line type: ${titleCase(state.newKind)}`);
    return;
  }
  if (path === "setting.newArrow") { state.newArrow = input.value; return; }
  if (path === "setting.newMarker") { state.newMarker = input.value; renderInspector(); return; }
  if (path === "setting.newMarkerSize") { state.newMarkerSize = clamp(Number(input.value) || 22, 6, 60); input.value = String(state.newMarkerSize); return; }
  if (path === "setting.loopMode") {
    state.loopMode = input.value;
    state.connectionStart = null;
    renderAll();
    return;
  }
  if (path === "edge.momentumEnabled") {
    const edge = edgeById(state.selected);
    if (edge) commit(() => { edge.momentum = input.checked ? { label: "", direction: "forward", side: edge.labelOffset < 0 ? "right" : "left", color: edge.color, start: 0.2, end: 0.8 } : null; }, "Momentum annotation changed");
    return;
  }
  const [scope, attribute] = path.split(".");
  const target = scope === "style" ? state.document.style : scope === "vertex" ? vertexById(state.selected) : scope === "annotation" ? annotationById(state.selected) : scope === "momentum" ? edgeById(state.selected)?.momentum : edgeById(state.selected);
  if (!target) return;
  let value = input.value;
  if (input.type === "number") {
    value = Number(value);
    if (!Number.isFinite(value)) { renderInspector(); return; }
    value = clamp(value, Number(input.min), Number(input.max));
    if (scope === "vertex" && (attribute === "x" || attribute === "y") && state.snap) {
      value = snapCoordinate(value, 20, attribute === "x" ? 700 : 460);
    }
  }
  if (attribute === "bundle") value = Number(value);
  if (scope === "momentum" && (attribute === "start" || attribute === "end")) value /= 100;
  commit(() => {
    target[attribute] = value;
    if (scope === "momentum") {
      if (attribute === "start") target.end = Math.max(target.end, Math.min(1, value + 0.05));
      if (attribute === "end") target.start = Math.min(target.start, Math.max(0, value - 0.05));
    }
    if (scope === "vertex" && attribute === "marker") target.visible = value !== "none";
  });
}

function applyTheme(theme) {
  state.theme = ["automatic", "light", "dark"].includes(theme) ? theme : "dark";
  document.body.dataset.theme = state.theme;
  persistSettings();
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]");
    if (action) { runAction(action.dataset.action); return; }
    const tool = event.target.closest("[data-tool]");
    if (tool) { closeMenus(); $(".annotation-tools")?.removeAttribute("open"); setTool(tool.dataset.tool); return; }
    const projectDelete = event.target.closest("[data-delete-project]");
    if (projectDelete) {
      const project = state.projects.find((item) => item.id === projectDelete.dataset.deleteProject);
      if (project) {
        $("#delete-project-dialog").dataset.projectId = project.id;
        $("#delete-project-name").textContent = project.id === state.activeProjectId ? state.document.title : project.diagram.title;
        $("#delete-project-dialog").showModal();
      }
      return;
    }
    const project = event.target.closest("[data-project]");
    if (project) {
      if (event.detail >= 2) { openRenameDialog(project.dataset.project); return; }
      const selected = state.projects.find((item) => item.id === project.dataset.project);
      if (selected && selected.id !== state.activeProjectId) replaceDocument(selected.diagram, "Diagram opened", selected.id);
      return;
    }
    const object = event.target.closest("[data-object]");
    if (object) {
      state.selected = object.dataset.object;
      state.connectionStart = null;
      state.tool = "select";
      renderAll();
      return;
    }
    if (!event.target.closest("details.menu")) closeMenus();
  });

  $$("details.menu").forEach((details) => details.addEventListener("toggle", () => {
    if (details.open) $$("details.menu").forEach((other) => { if (other !== details) other.open = false; });
  }));

  $("#inspector").addEventListener("change", (event) => inspectorChanged(event.target));
  $("#inspector").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("input")) event.target.blur();
  });

  $("#menu-snap").addEventListener("change", (event) => setSnap(event.target.checked));
  $("#menu-grid").addEventListener("change", (event) => {
    state.showGrid = event.target.checked;
    persistSettings();
    renderAll();
  });
  $("#menu-figure-panel").addEventListener("change", (event) => {
    state.showFigurePanel = event.target.checked; persistSettings(); renderAll();
  });
  $("#menu-template").addEventListener("change", (event) => {
    const index = Number(event.target.value);
    if (event.target.value !== "" && state.templates[index]) replaceDocument(state.templates[index], "Starting point loaded");
    event.target.value = ""; closeMenus();
  });
  $("#menu-grid-size").addEventListener("change", (event) => {
    state.gridSize = Number(event.target.value);
    persistSettings();
    setStatus(`Grid spacing: ${state.gridSize} units`);
    renderAll();
  });
  $("#menu-theme").addEventListener("change", (event) => applyTheme(event.target.value));
  $("#export-format").addEventListener("change", updateExportOptions);
  $("#latex-format").addEventListener("change", refreshLatex);
  $("#copy-latex").addEventListener("click", () => copyText(state.latexSource, "LaTeX copied"));
  $("#copy-standalone").addEventListener("click", () => copyText(state.standaloneSource, "Test document copied"));
  $("#diagram-title").addEventListener("click", () => openRenameDialog());

  $("#rename-form").addEventListener("submit", (event) => {
    if (event.submitter?.value !== "default") return;
    event.preventDefault();
    const title = $("#rename-input").value.trim();
    if (!title) { notify("The diagram title cannot be empty."); return; }
    const projectId = $("#rename-dialog").dataset.projectId;
    if (projectId === state.activeProjectId) commit((documentModel) => { documentModel.title = title; }, "Diagram renamed");
    else {
      const project = state.projects.find((item) => item.id === projectId);
      if (project) { project.diagram.title = title; persistProject(); renderLists(); }
    }
    $("#rename-dialog").close();
  });
  $("#figure-style-form").addEventListener("submit", (event) => {
    if (event.submitter?.value !== "apply") return;
    event.preventDefault();
    const before = clone(state.document);
    state.document.style = { widthMm: Number($("#figure-width").value), strokePt: Number($("#figure-stroke").value), fontPt: Number($("#figure-font").value) };
    if ($("#figure-snap").checked && !state.snap) for (const vertex of state.document.vertices) {
      vertex.x = snapCoordinate(vertex.x, 20, 700); vertex.y = snapCoordinate(vertex.y, 20, 460);
    }
    state.snap = $("#figure-snap").checked;
    state.showGrid = $("#figure-grid").checked;
    persistSettings(); record(before, "Figure style updated"); renderAll();
    $("#figure-style-dialog").close();
  });
  $("#delete-project-form").addEventListener("submit", (event) => {
    if (event.submitter?.value !== "delete") return;
    event.preventDefault(); deleteProject($("#delete-project-dialog").dataset.projectId); $("#delete-project-dialog").close();
  });
  $("#export-form").addEventListener("submit", (event) => {
    if (event.submitter?.value !== "default") return;
    event.preventDefault();
    exportDiagram();
  });
  $("#project-file").addEventListener("change", async (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (!file) return;
    try { await openProject(file); } catch (error) { notify(error.message); }
  });

  const canvas = $("#diagram-canvas");
  canvas.addEventListener("pointerdown", canvasDown);
  canvas.addEventListener("pointermove", canvasMove);
  canvas.addEventListener("pointerup", canvasUp);
  canvas.addEventListener("pointercancel", canvasUp);

  $$(".sidebar-resizer").forEach((resizer) => {
    resizer.addEventListener("pointerdown", beginSidebarResize);
    resizer.addEventListener("pointermove", moveSidebarResize);
    resizer.addEventListener("pointerup", endSidebarResize);
    resizer.addEventListener("pointercancel", endSidebarResize);
    resizer.addEventListener("keydown", resizeSidebarWithKeyboard);
  });
  window.addEventListener("resize", applySidebarWidths);

  document.addEventListener("keydown", (event) => {
    const editing = event.target.closest("input, textarea, select, [contenteditable='true']");
    const dialogOpen = $("dialog[open]");
    if (editing || dialogOpen) return;
    const key = event.key.toLowerCase();
    if (event.metaKey || event.ctrlKey) {
      if (key === "n") { event.preventDefault(); replaceDocument(blankDiagram(), "New blank diagram"); }
      else if (key === "o") { event.preventDefault(); $("#project-file").click(); }
      else if (key === "s") { event.preventDefault(); saveProject(); }
      else if (key === "e") { event.preventDefault(); updateExportOptions(); $("#export-dialog").showModal(); }
      else if (key === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); }
      return;
    }
    if ({ v: "select", a: "vertex", c: "connect", l: "loop" }[key]) {
      setTool({ v: "select", a: "vertex", c: "connect", l: "loop" }[key]);
      return;
    }
    if (key === "delete" || key === "backspace") {
      event.preventDefault();
      removeSelected();
      return;
    }
    if (key === "escape") {
      state.selected = null;
      state.connectionStart = null;
      setTool("select");
      return;
    }
    if (["arrowleft", "arrowright", "arrowup", "arrowdown"].includes(key)) {
      const vertex = vertexById(state.selected);
      if (!vertex) return;
      event.preventDefault();
      const before = clone(state.document);
      const distance = state.snap ? state.gridSize * (event.shiftKey ? 2 : 1) : (event.shiftKey ? 10 : 1);
      if (key === "arrowleft") vertex.x = state.snap ? snapCoordinate(vertex.x - distance, 20, 700) : Math.max(20, vertex.x - distance);
      if (key === "arrowright") vertex.x = state.snap ? snapCoordinate(vertex.x + distance, 20, 700) : Math.min(700, vertex.x + distance);
      if (key === "arrowup") vertex.y = state.snap ? snapCoordinate(vertex.y - distance, 20, 460) : Math.max(20, vertex.y - distance);
      if (key === "arrowdown") vertex.y = state.snap ? snapCoordinate(vertex.y + distance, 20, 460) : Math.min(460, vertex.y + distance);
      record(before, "Vertex moved");
    }
  });
}

function loadSettings() {
  try {
    const settings = JSON.parse(localStorage.getItem(SETTINGS_STORE) || "{}");
    if (typeof settings.snap === "boolean") state.snap = settings.snap;
    if (typeof settings.showGrid === "boolean") state.showGrid = settings.showGrid;
    if (typeof settings.showFigurePanel === "boolean") state.showFigurePanel = settings.showFigurePanel;
    if ([10, 20, 40].includes(settings.gridSize)) state.gridSize = settings.gridSize;
    if (["automatic", "light", "dark"].includes(settings.theme)) state.theme = settings.theme;
    if (Number.isFinite(settings.libraryWidth)) state.libraryWidth = settings.libraryWidth;
    if (Number.isFinite(settings.inspectorWidth)) state.inspectorWidth = settings.inspectorWidth;
  } catch (_error) {
    // Defaults remain usable when browser storage is unavailable.
  }
  applySidebarWidths();
  applyTheme(state.theme);
}

async function restoreDocument(fallback) {
  try {
    const saved = JSON.parse(localStorage.getItem(PROJECTS_STORE) || "null");
    if (saved) {
      if (!Array.isArray(saved.projects) || !saved.projects.length) throw Error("Invalid project list.");
      const projects = [];
      for (const item of saved.projects) {
        if (typeof item.id !== "string" || !item.id) throw Error("Invalid project ID.");
        const response = await api("/api/validate", { diagram: item.diagram });
        projects.push({ id: item.id, diagram: (await response.json()).diagram });
      }
      if (new Set(projects.map((item) => item.id)).size !== projects.length) throw Error("Duplicate project ID.");
      const active = projects.find((item) => item.id === saved.activeId);
      if (!active) throw Error("Missing active project.");
      state.projects = projects;
      state.activeProjectId = active.id;
      setStatus("Recovered browser projects");
      return clone(active.diagram);
    }
  } catch (_error) { notify("The browser project list could not be restored. Trying the previous autosave."); }
  let documentModel = fallback;
  try {
    const saved = localStorage.getItem(STORE);
    if (saved) {
      const response = await api("/api/validate", { diagram: JSON.parse(saved) });
      documentModel = (await response.json()).diagram;
      setStatus("Recovered browser autosave");
    }
  } catch (_error) { notify("The previous browser draft could not be restored. A starting template was loaded instead."); }
  state.activeProjectId = uuid();
  state.projects = [{ id: state.activeProjectId, diagram: clone(documentModel) }];
  return documentModel;
}

async function initialize() {
  loadSettings();
  bindEvents();
  try {
    const response = await fetch("/api/bootstrap");
    if (!response.ok) throw new Error("The web app could not load its startup data.");
    const bootstrap = await response.json();
    state.token = bootstrap.token;
    state.version = bootstrap.version;
    state.templates = bootstrap.templates;
    $("#menu-template").innerHTML += state.templates.map((item, index) => `<option value="${index}">${escapeXml(item.title)}</option>`).join("");
    state.latexFormats = bootstrap.latexFormats;
    $("#version").textContent = `Version ${bootstrap.version} · Browser edition`;
    $("#latex-format").innerHTML = bootstrap.latexFormats.map((option) => `<option value="${escapeXml(option.value)}">${escapeXml(option.label)}</option>`).join("");
    state.document = await restoreDocument(clone(state.templates[0]));
    renderAll();
    persistProject();
    $("#app").setAttribute("aria-busy", "false");
  } catch (error) {
    notify(error.message);
    $("#app").setAttribute("aria-busy", "false");
    showMessage("Could not start", error.message);
  }
}

initialize();
