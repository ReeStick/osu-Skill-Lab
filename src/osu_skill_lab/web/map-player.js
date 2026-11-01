import { pointAt } from "./map-parser.js";

export function createMapPlayer() {
  const $ = (id) => document.getElementById(id);
  const canvas = $("map-canvas"),
    ctx = canvas.getContext("2d"),
    density = $("density"),
    dc = density.getContext("2d");
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  let map = null,
    time = 0,
    playing = false,
    last = 0,
    frame = 0,
    speed = 1,
    audio = null,
    audioURL = null,
    worker = null,
    generation = 0,
    playAttempt = 0,
    timer = null,
    rejectPending = null;
  const probe = document.createElement("span");
  probe.hidden = true;
  document.body.append(probe);
  function colour(name) {
    probe.style.color = "var(" + name + ")";
    return getComputedStyle(probe).color;
  }
  let palette = {};
  function colours() {
    palette = {
      bg: colour("--field"),
      ink: colour("--ink"),
      muted: colour("--muted"),
      accent: colour("--accent"),
      body: colour("--slider"),
      line: colour("--line"),
    };
  }
  function controls(enabled) {
    for (const id of [
      "play",
      "back",
      "forward",
      "seek",
      "attach-audio",
      "replace-source",
    ])
      $(id).disabled = !enabled;
  }
  function stop() {
    playAttempt++;
    playing = false;
    if (audio) audio.pause();
    cancelAnimationFrame(frame);
    $("play").textContent = "▶ Смотреть";
  }
  function detachAudio() {
    if (audio) {
      audio.onloadedmetadata = null;
      audio.onerror = null;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    audio = null;
    if (audioURL) URL.revokeObjectURL(audioURL);
    audioURL = null;
    $("audio-file").value = "";
    $("audio-status").textContent = "Музыка — отдельным файлом";
  }
  function clear() {
    generation++;
    stop();
    if (worker) worker.terminate();
    if (rejectPending) rejectPending(Error("Просмотр отменён"));
    rejectPending = null;
    worker = null;
    clearTimeout(timer);
    detachAudio();
    map = null;
    time = 0;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    dc.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    dc.clearRect(0, 0, density.width, density.height);
    controls(false);
    $("preview-empty").hidden = false;
    $("preview-mode").hidden = true;
    $("seek").value = 0;
    $("time").textContent = "— / —";
    $("preview-status").textContent =
      "Файл для просмотра сверяется с checksum выбранной карты.";
  }
  async function attach(file, sha) {
    clear();
    const token = generation;
    $("preview-status").textContent = "Проверяем файл и готовим просмотр…";
    try {
      if (file.size > 4 * 1024 * 1024) throw Error("Файл больше 4 MiB");
      const bytes = await file.arrayBuffer();
      if (token !== generation) return false;
      const result = await new Promise((resolve, reject) => {
        rejectPending = reject;
        worker = new Worker("/lab/assets/map-preview-worker.js", {
          type: "module",
        });
        worker.onmessage = ({ data }) =>
          data.error ? reject(Error(data.error)) : resolve(data.map);
        worker.onerror = () => reject(Error("Ошибка подготовки предпросмотра"));
        timer = setTimeout(
          () => reject(Error("Карта слишком сложная для предпросмотра")),
          15000,
        );
        worker.postMessage({ bytes, expectedSha: sha }, [bytes]);
      });
      if (token !== generation) return false;
      map = result;
      time = Math.max(0, map.objects[0].t - 600);
      $("seek").max = map.end;
      controls(true);
      $("preview-empty").hidden = true;
      $("preview-mode").hidden = false;
      $("preview-status").textContent =
        "Checksum совпадает · исходный .osu доступен до закрытия вкладки";
      if (map.audioName)
        $("audio-status").textContent = "Аудио: " + map.audioName;
      draw();
      return true;
    } catch (error) {
      if (token === generation) $("preview-status").textContent = error.message;
      return false;
    } finally {
      if (token === generation) {
        clearTimeout(timer);
        rejectPending = null;
        if (worker) worker.terminate();
        worker = null;
      }
    }
  }
  function size(c) {
    const box = c.getBoundingClientRect(),
      dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(box.width * dpr)),
      h = Math.max(1, Math.round(box.height * dpr));
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    return { w: box.width, h: box.height, dpr };
  }
  function circle(x, y, r, fill, stroke, width = 2) {
    ctx.beginPath();
    ctx.arc(x, y, Math.max(0.1, r), 0, Math.PI * 2);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
    }
  }
  function pathLine(path, width, color) {
    ctx.beginPath();
    path.points.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = width;
    ctx.strokeStyle = color;
    ctx.stroke();
  }
  function format(ms) {
    const s = Math.floor(ms / 1000);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  function draw() {
    if (!map) return;
    const { w, h, dpr } = size(canvas);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const scale = Math.min(w / 600, h / 450),
      ox = (w - 512 * scale) / 2,
      oy = (h - 384 * scale) / 2;
    ctx.translate(ox, oy);
    ctx.scale(scale, scale);
    const r = 54.4 - 4.48 * map.cs,
      visible = map.objects.filter(
        (o) => o.t - map.pre <= time && o.end + 170 >= time,
      );
    for (let i = visible.length - 1; i >= 0; i--) {
      const o = visible[i],
        delta = o.t - time,
        fade =
          clamp((time - (o.t - map.pre)) / Math.min(400, map.pre), 0, 1) *
          clamp((o.end + 170 - time) / 170, 0, 1);
      ctx.globalAlpha = fade;
      if (o.kind === "spinner") {
        circle(256, 192, 115, null, palette.line, 6);
        circle(256, 192, 45, null, palette.accent, 3);
        if (time >= o.t) {
          ctx.beginPath();
          ctx.arc(
            256,
            192,
            115,
            -Math.PI / 2,
            -Math.PI / 2 +
              2 * Math.PI * clamp((time - o.t) / (o.end - o.t || 1), 0, 1),
          );
          ctx.strokeStyle = palette.accent;
          ctx.lineWidth = 6;
          ctx.stroke();
          const a = (time - o.t) / 180;
          circle(
            256 + 85 * Math.cos(a),
            192 + 85 * Math.sin(a),
            9,
            palette.accent,
          );
        }
        continue;
      }
      if (o.kind === "slider") {
        pathLine(o.path, r * 2, palette.accent);
        pathLine(o.path, r * 2 - 5, palette.body);
        const tail = pointAt(o.path, 1);
        circle(...tail, r - 4, null, palette.accent, 1);
        if (o.spans > 1 && time < o.end - o.span) {
          const endpoint =
            Math.max(0, Math.floor((time - o.t) / o.span)) % 2 === 0
              ? tail
              : [o.x, o.y];
          ctx.fillStyle = palette.ink;
          ctx.font = "24px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText("↶", ...endpoint);
        }
        if (time >= o.t && time <= o.end) {
          const elapsed = (time - o.t) / o.span,
            span = Math.min(o.spans - 1, Math.floor(elapsed)),
            progress = clamp(elapsed - span, 0, 1),
            p = pointAt(o.path, span % 2 ? 1 - progress : progress);
          circle(...p, r + 5, null, palette.ink, 2);
          circle(...p, 5, palette.ink);
        }
      }
      if (delta >= -120) {
        ctx.globalAlpha = fade * clamp((delta + 120) / 120, 0, 1);
        circle(o.x, o.y, r, palette.body, palette.accent, 2.5);
        ctx.fillStyle = palette.ink;
        ctx.font = "500 19px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(o.n), o.x, o.y);
        if (delta > 0)
          circle(
            o.x,
            o.y,
            r * (1 + (3 * delta) / map.pre),
            null,
            palette.accent,
            1.6,
          );
      }
    }
    ctx.globalAlpha = 1;
    const ds = size(density);
    dc.setTransform(ds.dpr, 0, 0, ds.dpr, 0, 0);
    dc.clearRect(0, 0, ds.w, ds.h);
    const bins = 100,
      counts = new Array(bins).fill(0);
    for (const o of map.objects)
      counts[Math.min(bins - 1, Math.floor((o.t / map.end) * bins))]++;
    const max = Math.max(1, ...counts);
    for (let i = 0; i < bins; i++) {
      dc.fillStyle = i / bins <= time / map.end ? palette.accent : palette.line;
      const bh = (counts[i] / max) * (ds.h - 3);
      dc.fillRect(
        (i * ds.w) / bins,
        ds.h - bh,
        Math.max(0.5, ds.w / bins - 1.5),
        bh,
      );
    }
    $("seek").value = time;
    $("seek").setAttribute("aria-valuetext", format(time));
    $("time").textContent = format(time) + " / " + format(map.end);
  }

  function seek(t) {
    if (!map) return;
    time = clamp(t, 0, map.end);
    if (audio) audio.currentTime = time / 1000;
    last = performance.now();
    draw();
  }
  function tick(now) {
    if (!playing || !map) return;
    const dt = now - last;
    last = now;
    if (audio && !audio.paused && !audio.ended) time = audio.currentTime * 1000;
    else time += dt * speed;
    if (time >= map.end) {
      time = map.end;
      stop();
    }
    draw();
    if (playing) frame = requestAnimationFrame(tick);
  }
  async function play() {
    if (!map) return;
    if (playing) {
      stop();
      return;
    }
    if (time >= map.end) seek(0);
    const token = ++playAttempt;
    $("play").disabled = true;
    try {
      if (
        audio &&
        (!Number.isFinite(audio.duration) || time / 1000 < audio.duration)
      ) {
        audio.currentTime = time / 1000;
        audio.playbackRate = speed;
        try {
          await audio.play();
        } catch {
          if (token === playAttempt)
            $("preview-status").textContent =
              "Аудио недоступно; просмотр без звука.";
        }
      }
      if (token !== playAttempt || !map) return;
      playing = true;
      last = performance.now();
      $("play").textContent = "Ⅱ Пауза";
      frame = requestAnimationFrame(tick);
    } finally {
      if (map) $("play").disabled = false;
    }
  }
  $("play").onclick = play;
  $("back").onclick = () => seek(time - 5000);
  $("forward").onclick = () => seek(time + 5000);
  $("seek").oninput = (e) => seek(Number(e.target.value));
  $("speed").onchange = (e) => {
    speed = Number(e.target.value);
    if (audio) audio.playbackRate = speed;
  };
  $("attach-audio").onclick = () => $("audio-file").click();
  $("audio-file").onchange = (e) => {
    const file = e.target.files[0];
    if (!file || !map) return;
    stop();
    detachAudio();
    if (file.size > 100 * 1024 * 1024) {
      $("preview-status").textContent = "Аудио больше 100 MiB";
      return;
    }
    const current = new Audio();
    audio = current;
    audioURL = URL.createObjectURL(file);
    audio.src = audioURL;
    audio.preload = "auto";
    audio.playbackRate = speed;
    audio.onloadedmetadata = () => {
      if (audio !== current) return;
      $("audio-status").textContent = file.name;
      audio.currentTime = time / 1000;
    };
    audio.onerror = () => {
      if (audio === current) {
        $("preview-status").textContent = "Не удалось прочитать аудио";
        detachAudio();
      }
    };
  };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
  });
  new ResizeObserver(() => {
    colours();
    draw();
  }).observe(canvas);
  new MutationObserver(() => {
    colours();
    draw();
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    colours();
    draw();
  });
  window.addEventListener("pagehide", clear);
  colours();
  controls(false);
  return { attach, clear, pause: stop, toggle: play };
}
