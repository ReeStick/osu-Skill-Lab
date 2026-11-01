// Approximate NM preview, not a gameplay decoder. Limits bound browser work.
const clamp = (x, a, b) => Math.max(a, Math.min(b, x)),
  dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
function bezier(points) {
  if (points.length > 64) throw Error("Слишком сложный слайдер для прототипа");
  const out = [];
  const n = Math.min(240, Math.max(24, points.length * 16));
  for (let s = 0; s <= n; s++) {
    const p = points.map((x) => x.slice()),
      t = s / n;
    for (let k = p.length - 1; k > 0; k--)
      for (let i = 0; i < k; i++) {
        p[i][0] += (p[i + 1][0] - p[i][0]) * t;
        p[i][1] += (p[i + 1][1] - p[i][1]) * t;
      }
    out.push(p[0]);
  }
  return out;
}
function curve(kind, p) {
  if (kind === "L") return p;
  if (kind === "P" && p.length === 3) {
    const [a, b, c] = p,
      d =
        2 *
        (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
    if (Math.abs(d) > 0.001) {
      const aa = a[0] ** 2 + a[1] ** 2,
        bb = b[0] ** 2 + b[1] ** 2,
        cc = c[0] ** 2 + c[1] ** 2;
      const x =
          (aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / d,
        y = (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / d;
      const start = Math.atan2(a[1] - y, a[0] - x),
        mid = Math.atan2(b[1] - y, b[0] - x),
        end = Math.atan2(c[1] - y, c[0] - x),
        tau = Math.PI * 2,
        norm = (v) => ((v % tau) + tau) % tau;
      let sweep = norm(end - start);
      if (norm(mid - start) > sweep) sweep -= tau;
      const r = Math.hypot(a[0] - x, a[1] - y);
      return Array.from({ length: 161 }, (_, i) => [
        x + r * Math.cos(start + (sweep * i) / 160),
        y + r * Math.sin(start + (sweep * i) / 160),
      ]);
    }
  }
  if (kind === "C") {
    const out = [];
    for (let i = 0; i < p.length - 1; i++) {
      const a = p[Math.max(0, i - 1)],
        b = p[i],
        c = p[i + 1],
        d = p[Math.min(p.length - 1, i + 2)];
      for (let j = 0; j < 30; j++) {
        const t = j / 30;
        out.push(
          [0, 1].map(
            (k) =>
              0.5 *
              (2 * b[k] +
                (-a[k] + c[k]) * t +
                (2 * a[k] - 5 * b[k] + 4 * c[k] - d[k]) * t * t +
                (-a[k] + 3 * b[k] - 3 * c[k] + d[k]) * t * t * t),
          ),
        );
      }
    }
    out.push(p[p.length - 1]);
    return out;
  }
  let out = [],
    segment = [p[0]];
  for (let i = 1; i < p.length; i++) {
    segment.push(p[i]);
    if (i === p.length - 1 || dist(p[i], p[i + 1]) < 0.001) {
      out.push(...bezier(segment));
      segment = [p[i]];
    }
  }
  return out.length ? out : p;
}
export function fitPath(points, length) {
  const out = [points[0]],
    cum = [0];
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const prev = out[out.length - 1],
      d = dist(prev, points[i]);
    if (d < 0.00001) continue;
    if (total + d >= length) {
      const q = (length - total) / d;
      out.push([
        prev[0] + q * (points[i][0] - prev[0]),
        prev[1] + q * (points[i][1] - prev[1]),
      ]);
      cum.push(length);
      return { points: out, cum, length };
    }
    total += d;
    out.push(points[i]);
    cum.push(total);
  }
  if (total < length && out.length > 1) {
    const a = out[out.length - 2],
      b = out[out.length - 1],
      d = dist(a, b),
      extra = length - total;
    out.push([
      b[0] + ((b[0] - a[0]) * extra) / d,
      b[1] + ((b[1] - a[1]) * extra) / d,
    ]);
    cum.push(length);
    total = length;
  }
  return { points: out, cum, length: total };
}
export function pointAt(path, fraction) {
  const target = clamp(fraction, 0, 1) * path.length;
  let a = 0,
    b = path.cum.length - 1;
  while (a < b) {
    const m = (a + b) >> 1;
    if (path.cum[m] < target) a = m + 1;
    else b = m;
  }
  if (a === 0) return path.points[0];
  const t = (target - path.cum[a - 1]) / (path.cum[a] - path.cum[a - 1] || 1),
    p = path.points[a - 1],
    q = path.points[a];
  return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
}
export function parseOsu(text) {
  if (!/^\uFEFF?osu file format v\d+/i.test(text))
    throw Error("Это не файл .osu");
  let section = "",
    meta = {},
    diff = {},
    general = {},
    timing = [],
    raw = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const l = rawLine.trim();
    if (!l || l.startsWith("//")) continue;
    if (l.startsWith("[")) {
      section = l;
      continue;
    }
    if (section === "[HitObjects]") raw.push(l);
    else if (section === "[TimingPoints]") {
      const v = l.split(",").map(Number);
      if (Number.isFinite(v[0]) && Number.isFinite(v[1]) && v[1] !== 0)
        timing.push({ t: v[0], beat: v[1], red: v[6] !== 0 });
    } else {
      const p = l.indexOf(":");
      if (p >= 0) {
        const target =
          section === "[Metadata]"
            ? meta
            : section === "[Difficulty]"
              ? diff
              : section === "[General]"
                ? general
                : null;
        if (target) target[l.slice(0, p)] = l.slice(p + 1).trim();
      }
    }
  }
  if (Number(general.Mode || 0) !== 0)
    throw Error("Поддерживается только osu!standard");
  if (!raw.length || raw.length > 20000)
    throw Error("Нужно от 1 до 20 000 объектов");
  timing.sort((a, b) => a.t - b.t);
  let tp = 0,
    beat = 500,
    sv = 1,
    combo = 0;
  const sorted = raw
      .map((l) => l.split(","))
      .sort((a, b) => Number(a[2]) - Number(b[2])),
    objects = [];
  let pointBudget = 0;
  for (const v of sorted) {
    let x = Number(v[0]),
      y = Number(v[1]),
      t = Number(v[2]),
      type = Number(v[3]);
    if (
      ![x, y, t, type].every(Number.isFinite) ||
      Math.abs(x) > 8192 ||
      Math.abs(y) > 8192 ||
      t < 0 ||
      t > 86400000
    )
      throw Error("Некорректные координаты или время объекта");
    while (tp < timing.length && timing[tp].t <= t) {
      const p = timing[tp++];
      if (p.red && p.beat > 0) {
        beat = p.beat;
        sv = 1;
      } else if (!p.red && p.beat < 0) sv = clamp(-100 / p.beat, 0.1, 10);
    }
    combo = type & 4 || !objects.length ? 1 : combo + 1;
    const o = { x, y, t, end: t, n: combo, kind: "circle" };
    if (type & 8) {
      o.kind = "spinner";
      o.end = Number(v[5]);
      if (!Number.isFinite(o.end) || o.end < t || o.end > 86400000)
        throw Error("Некорректный спиннер");
    } else if (type & 2) {
      const parts = (v[5] || "").split("|"),
        kind = parts.shift();
      if (!["L", "B", "P", "C"].includes(kind))
        throw Error("Неизвестный тип кривой");
      const p = [[x, y], ...parts.map((s) => s.split(":").map(Number))];
      if (
        p.length > 256 ||
        p.some(
          (q) =>
            q.length !== 2 ||
            !q.every(Number.isFinite) ||
            q.some((z) => Math.abs(z) > 8192),
        )
      )
        throw Error("Некорректная геометрия слайдера");
      const spans = Number(v[6]),
        length = Number(v[7]),
        mult = Number(diff.SliderMultiplier || 1.4);
      if (
        !Number.isInteger(spans) ||
        spans < 1 ||
        spans > 1000 ||
        !Number.isFinite(length) ||
        length <= 0 ||
        length > 100000 ||
        !Number.isFinite(mult) ||
        mult <= 0
      )
        throw Error("Некорректные параметры слайдера");
      o.path = fitPath(curve(kind, p), length);
      pointBudget += o.path.points.length;
      if (pointBudget > 1000000)
        throw Error("Карта слишком сложная для этого прототипа");
      o.span = (length / (mult * 100 * sv)) * beat;
      o.end = t + o.span * spans;
      o.spans = spans;
      o.kind = "slider";
      if (o.end > 86400000) throw Error("Слишком длинный слайдер");
    }
    objects.push(o);
  }
  const cs = Number(diff.CircleSize ?? 4),
    ar = Number(diff.ApproachRate ?? diff.OverallDifficulty ?? 7);
  if (!Number.isFinite(cs) || !Number.isFinite(ar))
    throw Error("Некорректные AR или CS");
  const pre =
    ar < 5 ? 1200 + (600 * (5 - ar)) / 5 : 1200 - (750 * (ar - 5)) / 5;
  return {
    title: meta.TitleUnicode || meta.Title || "Без названия",
    artist: meta.ArtistUnicode || meta.Artist || "",
    version: meta.Version || "",
    cs: clamp(cs, 0, 10),
    ar: clamp(ar, 0, 10),
    pre: clamp(pre, 450, 1800),
    objects,
    end: objects.reduce((n, o) => Math.max(n, o.end), 0) + 1000,
    audioName: general.AudioFilename || "",
  };
}
