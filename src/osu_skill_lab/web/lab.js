import { api, request } from "./api-client.js";
import { createMapPlayer } from "./map-player.js";
import { decisionBody, undoBody, labelName } from "./label-state.js";

const $ = (id) => document.getElementById(id);
const player = createMapPlayer();
const state = {
  rows: [],
  selected: null,
  tags: [],
  labels: null,
  mode: "browse",
  tag: "",
  cursor: null,
  q: "",
  loading: false,
  saving: false,
  uploading: false,
  undo: null,
  collectionGeneration: 0,
  labelGeneration: 0,
};
const sources = new Map(); // Only browser File references; no IndexedDB or server raw storage.
let toastTimer, searchTimer;
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 7000);
}
function remember(sha, file) {
  sources.delete(sha);
  sources.set(sha, file);
  let size = [...sources.values()].reduce((n, f) => n + f.size, 0);
  while (sources.size > 20 || size > 32 * 1024 * 1024) {
    const first = sources.keys().next().value;
    size -= sources.get(first).size;
    sources.delete(first);
  }
}
function busy() {
  return state.saving || state.uploading;
}
function ready() {
  return !!state.selected && state.labels !== null && !busy() && !state.loading;
}
function currentTag() {
  return state.tags.find((t) => t.id === state.tag);
}
function buttons() {
  for (const id of [
    "upload",
    "refresh",
    "search",
    "browse-mode",
    "review-mode",
    "review-tag",
    "new-tag",
    "review-new-tag",
  ])
    $(id).disabled = busy();
  $("next").disabled = !state.selected || busy() || state.loading;
  $("undo").disabled = !state.undo || busy();
  $("more").disabled = state.loading || busy();
  for (const id of ["yes", "no", "unsure", "clear-label"])
    $(id).disabled = !ready() || !state.tag;
  $("attach-map").disabled = !state.selected;
  document
    .querySelectorAll(".tag-button")
    .forEach((b) => (b.disabled = !ready()));
  document.querySelectorAll(".map-row").forEach((b) => (b.disabled = busy()));
}
function renderRows() {
  const rows =
    state.selected &&
    !state.rows.some((row) => row.analysis_id === state.selected.analysis_id)
      ? [state.selected, ...state.rows]
      : state.rows;
  $("map-list").replaceChildren(
    ...rows.map((row) => {
      const b = node("button", undefined, "map-row");
      b.dataset.id = row.analysis_id;
      b.setAttribute(
        "aria-pressed",
        String(row.analysis_id === state.selected?.analysis_id),
      );
      b.append(
        node("strong", row.title || "Без названия"),
        node("small", `${row.artist} · ${row.version}`),
      );
      b.onclick = () => {
        if (!busy()) select(row);
      };
      return b;
    }),
  );
  $("empty").hidden = !!state.rows.length || state.loading;
  $("more").hidden = state.cursor === null;
  buttons();
}
function renderDecision() {
  const focus = currentTag();
  $("review-description").textContent =
    focus?.description || "Создай тег и опиши, когда он встречается в карте.";
  $("review-current").textContent =
    state.labels === null && state.selected
      ? "Читаем разметку…"
      : `${focus?.name || "Тег"} — ${labelName(state.labels?.[state.tag]?.value)}`;
  for (const value of ["yes", "no", "unsure"])
    $(value).setAttribute(
      "aria-pressed",
      String(state.labels?.[state.tag]?.value === value),
    );
  $("tags").replaceChildren(
    ...state.tags.map((tag) => {
      const value = state.labels?.[tag.id]?.value;
      const b = node(
        "button",
        (value === "yes" ? "✓ " : "+ ") +
          tag.name +
          (["no", "unsure"].includes(value) ? ` · ${labelName(value)}` : ""),
        "tag-button",
      );
      b.setAttribute("aria-pressed", String(value === "yes"));
      b.setAttribute(
        "aria-label",
        `${tag.name}: ${labelName(value)}. ${tag.description}`,
      );
      b.onfocus = b.onmouseenter = () =>
        ($("tag-description").textContent = `${tag.name}: ${tag.description}`);
      b.onclick = () =>
        write(tag.id, value === "yes" ? "unreviewed" : "yes", false);
      return b;
    }),
  );
  if (!state.tags.length)
    $("tags").append(
      node("p", "Добавь первый тег с понятным определением.", "hint"),
    );
  buttons();
}
function renderSelected() {
  const row = state.selected;
  $("selected-title").textContent = row?.title || "Твоя коллекция карт";
  $("selected-subtitle").textContent = row
    ? `${row.artist} · ${row.version}`
    : "Добавь .osu, чтобы посмотреть карту и отметить её особенности.";
  $("osu-link").hidden = !row?.beatmap_id;
  if (row?.beatmap_id)
    $("osu-link").href = `https://osu.ppy.sh/beatmaps/${row.beatmap_id}`;
  const features = row?.features || {};
  const entries = [
    ["Объектов", features.hit_object_count],
    ["Кругов", features.circle_count],
    ["Слайдеров", features.slider_count],
    [
      "BPM (min / max)",
      features.red_bpm_min == null
        ? "—"
        : `${Math.round(features.red_bpm_min)} / ${Math.round(features.red_bpm_max)}`,
    ],
  ];
  $("map-features").replaceChildren(
    ...entries.flatMap(([key, value]) => [
      node("dt", key),
      node("dd", value ?? "—"),
    ]),
  );
  renderDecision();
  renderRows();
}
async function readLabels() {
  const row = state.selected,
    token = ++state.labelGeneration;
  state.labels = null;
  renderDecision();
  if (!row) return;
  $("save-status").textContent = "Читаем разметку…";
  try {
    const labels = await api(`/analyses/${row.analysis_id}/labels`);
    if (token !== state.labelGeneration) return;
    state.labels = labels;
    $("save-status").textContent = "Решения сохраняются автоматически";
    renderDecision();
  } catch (error) {
    if (token !== state.labelGeneration) return;
    $("save-status").textContent = "Не удалось прочитать метки. Нажми ↻.";
    toast(error.message);
    buttons();
  }
}
function select(row) {
  state.selected = row;
  player.clear();
  renderSelected();
  readLabels();
  const file = row && sources.get(row.sha256);
  if (file) player.attach(file, row.sha256);
}
async function collection(append = false) {
  if (state.saving) return;
  if (append && (state.cursor === null || state.loading)) return;
  const token = ++state.collectionGeneration,
    selectedId = state.selected?.analysis_id;
  state.loading = true;
  buttons();
  $("collection-status").textContent = "Загружаем…";
  try {
    const params = new URLSearchParams({
      q: state.q,
      after_id: append ? state.cursor : 0,
      limit: 50,
    });
    const page = await api("/collection?" + params);
    if (token !== state.collectionGeneration) return;
    state.rows = append ? [...state.rows, ...page.rows] : page.rows;
    state.cursor = page.next_cursor;
    $("connection").textContent = "Коллекция подключена";
    $("collection-status").textContent =
      `${state.rows.length}${state.cursor !== null ? "+" : ""} карт${state.q ? " по запросу" : ""}`;
    if (!append)
      select(
        state.rows.find((row) => row.analysis_id === selectedId) ||
          state.rows[0] ||
          null,
      );
    renderRows();
  } catch (error) {
    if (token !== state.collectionGeneration) return;
    $("connection").textContent = "Нет соединения";
    $("collection-status").textContent =
      "Не удалось обновить каталог. Повтори через ↻.";
    toast(error.message);
  } finally {
    if (token === state.collectionGeneration) {
      state.loading = false;
      buttons();
      $("empty").hidden = !!state.rows.length;
    }
  }
}
async function next() {
  if (!state.selected) return;
  let index = state.rows.findIndex(
    (row) => row.analysis_id === state.selected.analysis_id,
  );
  if (index < 0) {
    select(state.rows[0] || null);
    return;
  }
  if (index + 1 >= state.rows.length && state.cursor !== null)
    await collection(true);
  if (index + 1 < state.rows.length) select(state.rows[index + 1]);
  else
    $("save-status").textContent =
      "Конец списка. Можно выбрать другую карту или изменить поиск.";
}
async function write(tagId, value, advance) {
  if (!ready()) return;
  const row = state.selected,
    previous = state.labels[tagId] || null;
  state.saving = true;
  buttons();
  $("save-status").textContent = "Сохраняем…";
  let saved = false;
  try {
    const event = await api(
      `/tags/${tagId}/labels`,
      decisionBody(row, previous, value),
    );
    state.labels[tagId] = event;
    state.undo = { row, tagId, previous, saved: event };
    $("save-status").textContent = "Сохранено";
    saved = true;
  } catch (error) {
    toast(
      error.status === 409
        ? "Разметка изменилась в другой вкладке. Решение не перезаписано."
        : error.message,
    );
    // A lost response might still have committed: always reconcile before another write.
    state.undo = null;
    await readLabels();
  } finally {
    state.saving = false;
    renderDecision();
  }
  if (saved && advance) await next();
}
async function undo() {
  const action = state.undo;
  if (!action || busy()) return;
  state.saving = true;
  buttons();
  try {
    await api(`/tags/${action.tagId}/labels`, undoBody(action));
    state.undo = null;
    select(action.row);
    toast("Последнее решение отменено");
  } catch (error) {
    state.undo = null;
    toast(
      error.status === 409
        ? "После твоего решения появилась новая разметка. Отмена не выполнена."
        : error.message,
    );
    await readLabels();
  } finally {
    state.saving = false;
    buttons();
  }
}
function mode(value) {
  state.mode = value;
  $("browse-panel").hidden = value !== "browse";
  $("review-panel").hidden = value !== "review";
  $("browse-mode").setAttribute("aria-pressed", String(value === "browse"));
  $("review-mode").setAttribute("aria-pressed", String(value === "review"));
  $("next").textContent = value === "review" ? "Пропустить →" : "Следующая →";
  renderDecision();
}
async function tags() {
  try {
    state.tags = await api("/tags");
    if (!state.tags.some((tag) => tag.id === state.tag))
      state.tag = state.tags[0]?.id || "";
    $("review-tag").replaceChildren(
      ...state.tags.map((tag) => {
        const option = node("option", tag.name);
        option.value = tag.id;
        return option;
      }),
    );
    $("review-tag").value = state.tag;
    renderDecision();
  } catch (error) {
    toast(error.message);
  }
}
$("browse-mode").onclick = () => mode("browse");
$("review-mode").onclick = () => mode("review");
$("review-tag").onchange = (event) => {
  state.tag = event.target.value;
  renderDecision();
};
for (const value of ["yes", "no", "unsure"])
  $(value).onclick = () => write(state.tag, value, true);
$("clear-label").onclick = () => write(state.tag, "unreviewed", false);
$("undo").onclick = undo;
$("next").onclick = next;
$("refresh").onclick = () => {
  clearTimeout(searchTimer);
  state.q = $("search").value.trim();
  collection();
  tags();
};
$("more").onclick = () => collection(true);
$("search").oninput = () => {
  clearTimeout(searchTimer);
  state.q = $("search").value.trim();
  searchTimer = setTimeout(() => collection(), 250);
};
for (const id of ["new-tag", "review-new-tag"])
  $(id).onclick = () => {
    $("tag-error").textContent = "";
    $("tag-dialog").showModal();
    $("tag-name").focus();
  };
$("close-dialog").onclick = () => $("tag-dialog").close();
$("tag-form").onsubmit = async (event) => {
  event.preventDefault();
  $("create-tag").disabled = true;
  try {
    const tag = await api("/tags", {
      name: $("tag-name").value.trim(),
      description: $("tag-definition").value.trim(),
    });
    state.tag = tag.id;
    $("tag-dialog").close();
    $("tag-form").reset();
    await tags();
  } catch (error) {
    $("tag-error").textContent = error.message;
  } finally {
    $("create-tag").disabled = false;
  }
};
$("attach-map").onclick = $("replace-source").onclick = () =>
  $("preview-file").click();
$("preview-file").onchange = async (event) => {
  const file = event.target.files[0],
    row = state.selected;
  event.target.value = "";
  if (!file || !row) return;
  if (await player.attach(file, row.sha256)) remember(row.sha256, file);
};
$("upload").onclick = () => $("upload-files").click();
$("upload-files").onchange = async (event) => {
  const files = [...event.target.files];
  event.target.value = "";
  if (!files.length || busy()) return;
  if (files.length > 100) {
    toast("Выбери до 100 файлов за один импорт.");
    return;
  }
  clearTimeout(searchTimer);
  state.uploading = true;
  buttons();
  let last = null,
    count = 0;
  const failures = [];
  try {
    for (const file of files) {
      $("connection").textContent =
        `Импорт ${count + failures.length + 1} / ${files.length}`;
      try {
        if (file.size > 4 * 1024 * 1024) throw Error("Больше 4 MiB");
        const result = await request("/analyses", {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        });
        const b = result.beatmap;
        last = {
          analysis_id: result.id,
          input_id: b.input_id,
          sha256: b.sha256,
          beatmap_id: b.claimed_beatmap_id,
          beatmap_set_id: b.claimed_beatmap_set_id,
          title: b.title,
          artist: b.artist,
          version: b.difficulty_name,
          features: result.features,
        };
        remember(b.sha256, file);
        count++;
      } catch (error) {
        failures.push(`${file.name}: ${error.message}`);
      }
    }
    state.q = "";
    $("search").value = "";
    await collection();
    if (last) select(last);
    toast(`Добавлено: ${count}. Ошибок: ${failures.length}.`);
    if (failures.length) {
      $("collection-status").textContent = failures.join(" · ");
    }
  } finally {
    state.uploading = false;
    buttons();
  }
};
function theme(value) {
  document.documentElement.dataset.theme = value;
  $("theme").textContent = value === "dark" ? "☀ Светлая" : "☾ Тёмная";
}
let savedTheme;
try {
  savedTheme = localStorage.getItem("osu-lab-theme");
} catch {
  /* private mode */
}
theme(
  savedTheme === "light" || savedTheme === "dark"
    ? savedTheme
    : matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
);
$("theme").onclick = () => {
  const value =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  theme(value);
  try {
    localStorage.setItem("osu-lab-theme", value);
  } catch {
    /* optional */
  }
};
document.addEventListener("keydown", (event) => {
  if (
    event.repeat ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    $("tag-dialog").open ||
    /INPUT|TEXTAREA|SELECT|BUTTON|A/.test(event.target.tagName)
  )
    return;
  if (state.mode === "review" && ["1", "2", "3"].includes(event.key)) {
    event.preventDefault();
    write(state.tag, ["yes", "no", "unsure"][Number(event.key) - 1], true);
  }
});
renderSelected();
await Promise.all([tags(), collection()]);
