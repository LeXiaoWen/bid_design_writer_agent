import type { ThemeAppearance } from "./types";

// ============================================================
// 基础类型与工具
// ============================================================

type Rgb = { r: number; g: number; b: number };
type Hsl = { h: number; s: number; l: number };

export type AspectClass = "ultrawide" | "wide" | "landscape" | "square" | "portrait";
export type TaskMode = "ambient" | "banner" | "off";

export type ArtAnalysis = {
  width: number;
  height: number;
  ratio: number;
  wide: boolean;
  aspect: AspectClass;
  brightness: number;
  shell: "light" | "dark";
  safeArea: "left" | "right" | "center";
  focusX: number;
  focusY: number;
  taskMode: TaskMode;
  accentRgb: Rgb | null;
};

export type ThemePresentation = {
  palette: Record<string, string>;
  safeArea: "left" | "right" | "center";
  focusX: string;
  aspect: AspectClass;
  wide: boolean;
  taskMode: TaskMode;
  focusY: string;
  analysis: ArtAnalysis | null;
};

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

function hex(r: number, g: number, b: number): string {
  return `#${[r, g, b].map((c) => clamp(Math.round(c), 0, 255).toString(16).padStart(2, "0")).join("")}`;
}

function toHsl(r: number, g: number, b: number): Hsl {
  const [red, green, blue] = [r, g, b].map((c) => c / 255);
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === red) h = (green - blue) / d + (green < blue ? 6 : 0);
  else if (max === green) h = (blue - red) / d + 2;
  else h = (red - green) / d + 4;
  return { h: h * 60, s, l };
}

function toRgb(h: number, s: number, l: number): Rgb {
  const hue = ((h % 360) + 360) % 360 / 360;
  if (s === 0) return { r: l * 255, g: l * 255, b: l * 255 };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const ch = (t: number) => {
    if (t < 0) t += 1; if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return { r: ch(1 / 3) * 255, g: ch(0) * 255, b: ch(-1 / 3) * 255 };
}

function luminance(r: number, g: number, b: number): number {
  const lin = [r, g, b].map((c) => {
    const x = c / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

// ============================================================
// 24-bin HSL 直方图
// ============================================================

function hueHistogram(pixels: Uint8ClampedArray, w: number, h: number) {
  const bins = Array.from({ length: 24 }, () => ({ weight: 0, r: 0, g: 0, b: 0 }));
  let lightSum = 0;
  let count = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (pixels[i + 3] < 32) continue;
      const cr = pixels[i], cg = pixels[i + 1], cb = pixels[i + 2];
      const hsl = toHsl(cr, cg, cb);
      lightSum += luminance(cr, cg, cb);
      count++;
      if (hsl.s >= 0.16 && hsl.l >= 0.16 && hsl.l <= 0.86) {
        const bin = bins[Math.min(23, Math.floor(hsl.h / 15))];
        const wgt = hsl.s * (1 - Math.abs(hsl.l - 0.52) * 0.85);
        bin.weight += wgt; bin.r += cr * wgt; bin.g += cg * wgt; bin.b += cb * wgt;
      }
    }
  }
  const best = bins.reduce((a, b) => (b.weight > a.weight ? b : a), bins[0]);
  return {
    accentRgb: best.weight > 0 ? { r: best.r / best.weight, g: best.g / best.weight, b: best.b / best.weight } as Rgb : null,
    brightness: count ? lightSum / count : 0.5,
  };
}

// ============================================================
// 显著性检测
// ============================================================

function saliency(pixels: Uint8ClampedArray, w: number, h: number, brightness: number) {
  const samples: ({ light: number; sat: number } | null)[] = new Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (pixels[i + 3] < 32) { samples[y * w + x] = null; continue; }
      const hsl = toHsl(pixels[i], pixels[i + 1], pixels[i + 2]);
      samples[y * w + x] = { light: luminance(pixels[i], pixels[i + 1], pixels[i + 2]), sat: hsl.s };
    }
  }
  let salTotal = 0, salX = 0, salY = 0, leftI = 0, rightI = 0;
  const halfW = w / 2;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const s = samples[y * w + x];
      if (!s) continue;
      const prev = x > 0 ? samples[y * w + x - 1] : null;
      const above = y > 0 ? samples[(y - 1) * w + x] : null;
      const edge = (prev ? Math.abs(s.light - prev.light) : 0) + (above ? Math.abs(s.light - above.light) : 0);
      const wgt = 0.01 + Math.abs(s.light - brightness) * 0.48 + s.sat * 0.34 + edge * 0.28;
      salTotal += wgt;
      salX += (x + 0.5) / w * wgt;
      salY += (y + 0.5) / h * wgt;
      const info = edge * 0.42 + Math.abs(s.light - brightness) * 0.58;
      if (x < halfW) leftI += info; else rightI += info;
    }
  }
  return {
    focusX: salTotal ? clamp(salX / salTotal, 0.12, 0.88) : 0.5,
    focusY: salTotal ? clamp(salY / salTotal, 0.18, 0.82) : 0.5,
    leftInfo: leftI, rightInfo: rightI,
  };
}

// ============================================================
// 增强分析
// ============================================================

function enhancedAnalysis(image: HTMLImageElement): ArtAnalysis | null {
  const w = image.naturalWidth, h = image.naturalHeight;
  const ratio = w / h;
  if (!isFinite(ratio) || ratio <= 0) return null;

  const maxDim = 96;
  const sw = Math.max(24, Math.round(ratio >= 1 ? maxDim : maxDim * ratio));
  const sh = Math.max(24, Math.round(ratio >= 1 ? maxDim / ratio : maxDim));

  const canvas = document.createElement("canvas");
  canvas.width = sw; canvas.height = sh;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  ctx.drawImage(image, 0, 0, sw, sh);
  const pixels = ctx.getImageData(0, 0, sw, sh).data;

  const { accentRgb, brightness } = hueHistogram(pixels, sw, sh);
  const { focusX, focusY, leftInfo, rightInfo } = saliency(pixels, sw, sh, brightness);

  let safe: "left" | "right" | "center" = "center";
  if (leftInfo < rightInfo * 0.86) safe = "left";
  else if (rightInfo < leftInfo * 0.86) safe = "right";

  let fx = focusX;
  if (safe === "left") fx = Math.max(0.64, fx);
  if (safe === "right") fx = Math.min(0.36, fx);

  let aspect: AspectClass = "landscape";
  if (ratio >= 2.25) aspect = "ultrawide";
  else if (ratio >= 1.45) aspect = "wide";
  else if (ratio >= 1.08) aspect = "landscape";
  else if (ratio >= 0.9) aspect = "square";
  else aspect = "portrait";

  return {
    width: w, height: h, ratio,
    wide: ratio >= 1.75, aspect,
    brightness,
    shell: brightness >= 0.58 ? "light" : "dark",
    safeArea: safe,
    focusX: fx, focusY,
    taskMode: ratio >= 2.25 ? "banner" : "ambient",
    accentRgb,
  };
}

// ============================================================
// 缓存 (LRU, max 8)
// ============================================================

const cache = new Map<string, ArtAnalysis>();
const CACHE_MAX = 8;

function cacheKey(url: string): string {
  let hash = 0;
  for (let i = 0; i < url.length; i++) hash = ((hash << 5) - hash + url.charCodeAt(i)) | 0;
  return String(hash);
}

// ============================================================
// 构建 ThemePresentation
// ============================================================

export function deriveThemePresentation(
  sample: Rgb,
  appearance: ThemeAppearance,
  leftInfo = 1,
  rightInfo = 1,
  analysis: ArtAnalysis | null = null,
): ThemePresentation {
  const shell = appearance === "auto" ? (analysis?.shell ?? "light") : appearance;
  const hsl = toHsl(sample.r, sample.g, sample.b);
  const hue = hsl.s < 0.12 ? 214 : hsl.h;
  const sat = clamp(hsl.s, 0.34, 0.7);
  const accent = hex(...Object.values(toRgb(hue, sat, shell === "light" ? 0.42 : 0.66)) as [number, number, number]);
  const accentAlt = hex(...Object.values(toRgb(hue + 18, sat * 0.78, shell === "light" ? 0.56 : 0.74)) as [number, number, number]);

  const safeArea = analysis?.safeArea
    ?? (leftInfo < rightInfo * 0.86 ? "left" : rightInfo < leftInfo * 0.86 ? "right" : "center");
  const focusX = analysis?.focusX != null ? `${(analysis.focusX * 100).toFixed(0)}%`
    : safeArea === "left" ? "72%" : safeArea === "right" ? "28%" : "50%";
  const focusY = analysis?.focusY != null ? `${(analysis.focusY * 100).toFixed(0)}%` : "50%";

  return {
    safeArea, focusX, focusY,
    aspect: analysis?.aspect ?? "landscape",
    wide: analysis?.wide ?? false,
    taskMode: analysis?.taskMode ?? "ambient",
    analysis,
    palette: shell === "light"
      ? { "--theme-bg": "#f3f6f8", "--theme-panel": "#ffffff", "--theme-panel-soft": "#eef3f6", "--theme-text": "#1a1f24", "--theme-muted": "#4a5460", "--theme-accent": accent, "--theme-accent-alt": accentAlt }
      : { "--theme-bg": "#0e1319", "--theme-panel": "#1a2128", "--theme-panel-soft": "#222b33", "--theme-text": "#f4f7f9", "--theme-muted": "#bcc6cf", "--theme-accent": accent, "--theme-accent-alt": accentAlt },
  };
}

// ============================================================
// 公开 API
// ============================================================

export async function analyzeThemeImage(imageUrl: string, appearance: ThemeAppearance): Promise<ThemePresentation> {
  // 1. 加载图片
  let image: HTMLImageElement;
  try {
    image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("load error"));
      img.src = imageUrl;
    });
  } catch {
    return deriveThemePresentation({ r: 91, g: 123, b: 141 }, appearance);
  }

  // 2. 基础分析（48×30，始终执行）
  const cvs = document.createElement("canvas");
  cvs.width = 48; cvs.height = 30;
  const ctx = cvs.getContext("2d", { willReadFrequently: true });
  if (!ctx) return deriveThemePresentation({ r: 91, g: 123, b: 141 }, appearance);

  ctx.drawImage(image, 0, 0, cvs.width, cvs.height);
  const px = ctx.getImageData(0, 0, cvs.width, cvs.height).data;
  let r = 0, g = 0, b = 0, li = 0, ri = 0;
  for (let i = 0; i < px.length; i += 4) { r += px[i]; g += px[i + 1]; b += px[i + 2]; }
  const cnt = px.length / 4;
  const avg: Rgb = { r: r / cnt, g: g / cnt, b: b / cnt };
  for (let i = 0; i < px.length; i += 4) {
    const dev = Math.abs(px[i] - avg.r) + Math.abs(px[i + 1] - avg.g) + Math.abs(px[i + 2] - avg.b);
    if ((i / 4) % cvs.width < cvs.width / 2) li += dev; else ri += dev;
  }

  // 3. 增强分析（缓存 + 非阻塞）
  const key = cacheKey(imageUrl);
  const hit = cache.get(key);
  if (hit) return deriveThemePresentation(hit.accentRgb ?? avg, appearance, li, ri, hit);

  try {
    const ea = enhancedAnalysis(image);
    if (ea) {
      if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value!);
      cache.set(key, ea);
      return deriveThemePresentation(ea.accentRgb ?? avg, appearance, li, ri, ea);
    }
  } catch { /* ignore */ }

  return deriveThemePresentation(avg, appearance, li, ri);
}
