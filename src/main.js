const STORAGE_KEY = "colorgrab.history";
const MAX_HISTORY = 12;

const swatch = document.getElementById("swatch");
const swatchHex = document.getElementById("swatchHex");
const swatchRgb = document.getElementById("swatchRgb");
const pickBtn = document.getElementById("pickBtn");
const pickBtnLabel = document.getElementById("pickBtnLabel");
const eyedropperBtn = document.getElementById("eyedropperBtn");
const manualColor = document.getElementById("manualColor");
const supportNote = document.getElementById("supportNote");
const hexValue = document.getElementById("hexValue");
const rgbValue = document.getElementById("rgbValue");
const hslValue = document.getElementById("hslValue");
const winValue = document.getElementById("winValue");
const xyValue = document.getElementById("xyValue");
const relValue = document.getElementById("relValue");
const swatchXy = document.getElementById("swatchXy");
const swatchRel = document.getElementById("swatchRel");
const swatchRelSep = document.getElementById("swatchRelSep");
const shapeRow = document.getElementById("shapeRow");
const shapeLabel = document.getElementById("shapeLabel");
const shapePrimary = document.getElementById("shapePrimary");
const shapeSecondary = document.getElementById("shapeSecondary");
const historyEl = document.getElementById("history");
const toast = document.getElementById("toast");

const MODE_COPY = {
  point: {
    label: "Pick color + window",
    hint: "Point: color, X11 window id, screen + window-relative coords.",
  },
  rect: {
    label: "Select rectangle",
    hint: "Rectangle: click first corner, move to preview, click opposite corner. Esc / right-click cancels.",
  },
  circle: {
    label: "Select circle",
    hint: "Circle: click center, move to preview radius, click the edge. Esc / right-click cancels.",
  },
};

const state = {
  mode: "point",
  hex: "#3DFFA8",
  rgb: "61, 255, 168",
  rgbCss: "rgb(61, 255, 168)",
  hsl: "152°, 100%, 62%",
  windowId: "",
  x: null,
  y: null,
  relX: null,
  relY: null,
  xyText: "",
  geomText: "",
  relText: "",
  relGeomText: "",
  shapePrimaryText: "",
  shapeSecondaryText: "",
  history: loadHistory(),
  nativeReady: false,
};

function loadHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((c) => /^#[0-9A-Fa-f]{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

function saveHistory() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history));
}

function normalizeHex(input) {
  let hex = String(input).trim().toUpperCase();
  if (!hex.startsWith("#")) hex = `#${hex}`;
  if (/^#[0-9A-F]{3}$/.test(hex)) {
    hex = `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`;
  }
  if (!/^#[0-9A-F]{6}$/.test(hex)) return null;
  return hex;
}

function formatX11Id(raw) {
  if (raw == null || raw === "") return "";
  const text = String(raw).trim();
  let n;
  if (/^0x/i.test(text)) n = Number.parseInt(text, 16);
  else n = Number.parseInt(text, 10);
  if (!Number.isFinite(n)) return "";
  return `0x${n.toString(16).padStart(8, "0")}`;
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return {
    r: (n >> 16) & 255,
    g: (n >> 8) & 255,
    b: n & 255,
  };
}

function rgbToHsl({ r, g, b }) {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case rn:
        h = ((gn - bn) / d + (gn < bn ? 6 : 0)) * 60;
        break;
      case gn:
        h = ((bn - rn) / d + 2) * 60;
        break;
      default:
        h = ((rn - gn) / d + 4) * 60;
    }
  }

  return {
    h: Math.round(h),
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
}

function setWindowId(rawId) {
  state.windowId = formatX11Id(rawId);
  winValue.textContent = state.windowId || "—";
}

function setCoords(x, y, relX, relY) {
  const xi = Number.isFinite(Number(x)) ? Math.round(Number(x)) : null;
  const yi = Number.isFinite(Number(y)) ? Math.round(Number(y)) : null;
  const rxi = Number.isFinite(Number(relX)) ? Math.round(Number(relX)) : null;
  const ryi = Number.isFinite(Number(relY)) ? Math.round(Number(relY)) : null;

  state.x = xi;
  state.y = yi;
  state.relX = rxi;
  state.relY = ryi;

  if (xi == null || yi == null) {
    state.xyText = "";
    state.geomText = "";
    xyValue.textContent = "screen —, —";
    swatchXy.textContent = "—, —";
  } else {
    state.xyText = `${xi}, ${yi}`;
    state.geomText = `+${xi}+${yi}`;
    xyValue.textContent = `screen ${state.xyText}`;
    swatchXy.textContent = state.xyText;
  }

  if (rxi == null || ryi == null) {
    state.relText = "";
    state.relGeomText = "";
    relValue.textContent = "window —, —";
    swatchRel.hidden = true;
    swatchRelSep.hidden = true;
    swatchRel.textContent = "";
  } else {
    state.relText = `${rxi}, ${ryi}`;
    state.relGeomText = `+${rxi}+${ryi}`;
    relValue.textContent = `window ${state.relText}`;
    swatchRel.hidden = false;
    swatchRelSep.hidden = false;
    swatchRel.textContent = `win ${state.relText}`;
  }
}

function clearShape() {
  state.shapePrimaryText = "";
  state.shapeSecondaryText = "";
  shapeRow.hidden = true;
  shapePrimary.textContent = "—";
  shapeSecondary.textContent = "—";
}

function setShape(data) {
  if (!data?.shape) {
    clearShape();
    return;
  }

  shapeRow.hidden = false;
  if (data.shape === "rect") {
    shapeLabel.textContent = "RECT";
    state.shapePrimaryText = data.boxText || `${data.x},${data.y} ${data.width}×${data.height}`;
    state.shapeSecondaryText = data.geom || "";
    shapePrimary.textContent = state.shapePrimaryText;
    shapeSecondary.textContent = state.shapeSecondaryText || "—";
  } else if (data.shape === "circle") {
    shapeLabel.textContent = "CIRCLE";
    state.shapePrimaryText = data.boxText || `center ${data.cx},${data.cy} r=${data.r}`;
    state.shapeSecondaryText = data.geom || "";
    shapePrimary.textContent = state.shapePrimaryText;
    shapeSecondary.textContent = state.shapeSecondaryText
      ? `bbox ${state.shapeSecondaryText}`
      : "—";
  } else {
    clearShape();
  }
}

function setColor(input, { pushHistory = true, windowId, x, y, relX, relY } = {}) {
  const hex = normalizeHex(input);
  if (!hex) return;

  const rgb = hexToRgb(hex);
  const hsl = rgbToHsl(rgb);

  state.hex = hex;
  state.rgb = `${rgb.r}, ${rgb.g}, ${rgb.b}`;
  state.rgbCss = `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
  state.hsl = `${hsl.h}°, ${hsl.s}%, ${hsl.l}%`;

  document.documentElement.style.setProperty("--current", hex);
  swatch.style.backgroundColor = hex;
  swatch.classList.remove("is-flash");
  void swatch.offsetWidth;
  swatch.classList.add("is-flash");

  hexValue.textContent = hex;
  rgbValue.textContent = state.rgbCss;
  hslValue.textContent = state.hsl;
  swatchHex.textContent = hex;
  swatchRgb.textContent = state.rgbCss;
  manualColor.value = hex.toLowerCase();

  if (windowId !== undefined) {
    setWindowId(windowId);
  }
  if (x !== undefined || y !== undefined || relX !== undefined || relY !== undefined) {
    setCoords(
      x !== undefined ? x : state.x,
      y !== undefined ? y : state.y,
      relX !== undefined ? relX : state.relX,
      relY !== undefined ? relY : state.relY,
    );
  }

  if (pushHistory) {
    state.history = [hex, ...state.history.filter((c) => c !== hex)].slice(0, MAX_HISTORY);
    saveHistory();
    renderHistory();
  }
}

function applyWindowFromData(data) {
  const win =
    data.x11WindowId ||
    (data.windowId && /^0x/i.test(String(data.windowId)) ? data.windowId : "") ||
    "";
  setWindowId(win);
  return win;
}

function renderHistory() {
  historyEl.innerHTML = "";
  if (state.history.length === 0) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "Picked colors land here.";
    historyEl.appendChild(empty);
    return;
  }

  for (const color of state.history) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-chip";
    btn.style.setProperty("--chip", color);
    btn.title = color;
    btn.setAttribute("aria-label", `Restore ${color}`);
    btn.addEventListener("click", () => setColor(color, { pushHistory: false }));
    historyEl.appendChild(btn);
  }
}

function showToast(message) {
  toast.hidden = false;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toast.classList.remove("show");
  }, 1800);
}

async function copyFormat(kind) {
  const map = {
    hex: state.hex,
    rgb: state.rgbCss,
    hsl: "",
    win: state.windowId,
    xy: state.xyText,
    geom: state.geomText,
    rel: state.relText,
    relGeom: state.relGeomText,
    shapePrimary: state.shapePrimaryText,
    shapeSecondary: state.shapeSecondaryText,
  };

  if (kind === "hsl") {
    const [h, s, l] = state.hsl.replaceAll("°", "").replaceAll("%", "").split(",").map((p) => p.trim());
    map.hsl = `hsl(${h}, ${s}%, ${l}%)`;
  }

  const text = map[kind];
  if (!text || text === "—" || text === "—, —") {
    showToast("Nothing to copy yet");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    const btn = document.querySelector(`[data-copy="${kind}"]`);
    if (btn) {
      const previous = btn.textContent;
      btn.classList.add("copied");
      btn.textContent = "OK";
      setTimeout(() => {
        btn.classList.remove("copied");
        btn.textContent = previous;
      }, 1100);
    }
    showToast(`Copied ${text}`);
  } catch {
    showToast("Clipboard blocked");
  }
}

function setMode(mode) {
  if (!MODE_COPY[mode]) return;
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    const active = btn.dataset.mode === mode;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });
  pickBtnLabel.textContent = MODE_COPY[mode].label;
  if (state.nativeReady) {
    supportNote.textContent = MODE_COPY[mode].hint;
  }
  eyedropperBtn.hidden = !(mode === "point" && window.EyeDropper);
  manualColor.closest(".manual").hidden = mode !== "point";
}

async function pickPoint() {
  supportNote.textContent = "Click any pixel on screen…";
  const res = await fetch("/api/grab", { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Native grab failed");

  clearShape();
  const win = applyWindowFromData(data);
  setColor(data.hex, {
    windowId: win,
    x: data.x,
    y: data.y,
    relX: data.relX,
    relY: data.relY,
  });

  const xyBit =
    Number.isFinite(Number(data.x)) && Number.isFinite(Number(data.y))
      ? ` @ ${Math.round(Number(data.x))},${Math.round(Number(data.y))}`
      : "";
  const relBit =
    Number.isFinite(Number(data.relX)) && Number.isFinite(Number(data.relY))
      ? ` (win ${Math.round(Number(data.relX))},${Math.round(Number(data.relY))})`
      : "";
  showToast(`Grabbed ${data.hex}${xyBit}${relBit}`);
  supportNote.textContent = win
    ? `Window ${formatX11Id(win)}${xyBit}${relBit}`
    : data.windowNote || "Color ok — no X11 window id (try an XWayland app).";
}

async function pickShape(kind) {
  supportNote.textContent =
    kind === "rect"
      ? "Click first corner, move, click opposite corner…"
      : "Click center, move, click edge…";
  const res = await fetch(`/api/grab/${kind}`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Shape grab failed");

  setShape(data);
  const win = applyWindowFromData(data);

  // Anchor XY readout on rect origin or circle center.
  const ax = data.shape === "circle" ? data.cx : data.x;
  const ay = data.shape === "circle" ? data.cy : data.y;
  setCoords(ax, ay, data.relX, data.relY);

  const summary =
    data.shape === "rect"
      ? `Rect ${data.width}×${data.height} @ ${data.x},${data.y}`
      : `Circle r=${data.r} @ ${data.cx},${data.cy}`;
  showToast(summary);
  supportNote.textContent = win ? `${summary} · ${formatX11Id(win)}` : summary;
}

async function pickNative() {
  pickBtn.disabled = true;
  eyedropperBtn.disabled = true;
  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.disabled = true;
  });
  try {
    if (state.mode === "rect") {
      await pickShape("rect");
    } else if (state.mode === "circle") {
      await pickShape("circle");
    } else {
      await pickPoint();
    }
  } catch (err) {
    showToast(err.message || "Grab failed");
    supportNote.textContent =
      err.message?.includes("cancel")
        ? "Selection cancelled."
        : "Native grab failed. Check the terminal running npm run dev.";
  } finally {
    pickBtn.disabled = false;
    eyedropperBtn.disabled = false;
    document.querySelectorAll(".mode-btn").forEach((b) => {
      b.disabled = false;
    });
  }
}

async function pickEyedropper() {
  if (!window.EyeDropper) {
    showToast("EyeDropper not supported — use the color well");
    manualColor.click();
    return;
  }

  eyedropperBtn.disabled = true;
  pickBtn.disabled = true;
  try {
    const dropper = new EyeDropper();
    const result = await dropper.open();
    clearShape();
    setColor(result.sRGBHex);
    showToast("Color only — window id needs native pick");
  } catch (err) {
    if (err?.name !== "AbortError") {
      showToast("Pick cancelled or failed");
    }
  } finally {
    eyedropperBtn.disabled = false;
    pickBtn.disabled = false;
  }
}

async function probeNative() {
  try {
    const res = await fetch("/api/grab", { method: "OPTIONS" });
    state.nativeReady = res.status === 204 || res.headers.get("Allow")?.includes("POST");
  } catch {
    state.nativeReady = location.protocol !== "file:";
  }
}

function initSupport() {
  if (state.nativeReady) {
    setMode(state.mode);
  } else if (window.EyeDropper) {
    supportNote.textContent = "Run npm run dev for window ids and shapes. Browser eyedropper is color-only.";
    pickBtnLabel.textContent = "Browser eyedropper";
    eyedropperBtn.hidden = false;
  } else {
    supportNote.textContent = "Open via npm run dev for full grab, or use the color well.";
    pickBtnLabel.textContent = "Open color well";
  }
}

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

pickBtn.addEventListener("click", () => {
  if (state.nativeReady) {
    pickNative();
  } else if (window.EyeDropper && state.mode === "point") {
    pickEyedropper();
  } else if (state.mode === "point") {
    manualColor.click();
  } else {
    showToast("Shape grab needs npm run dev");
  }
});
eyedropperBtn.addEventListener("click", pickEyedropper);
manualColor.addEventListener("input", (e) => setColor(e.target.value));
document.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", () => copyFormat(btn.dataset.copy));
});

await probeNative();
initSupport();
setColor(state.history[0] || "#3DFFA8", { pushHistory: false });
setCoords(null, null, null, null);
clearShape();
renderHistory();
