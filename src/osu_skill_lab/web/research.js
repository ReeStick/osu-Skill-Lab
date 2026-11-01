import { confusion, explainScore } from './score-core.js';

const $ = (id) => document.getElementById(id);
const state = {
  tags: [],
  tag: null,
  data: null,
  selected: null,
  scores: [],
  mode: 'rule',
  rules: [],
  models: [],
  model: null,
  manual: null,
  threshold: 0.5,
  generation: 0,
  loadGeneration: 0,
  modelGeneration: 0,
  loading: false,
  saving: false,
  training: false,
  undo: null,
  visibleLimit: 200,
  mapLabels: new Map(),
  labelRequests: new Map(),
  labelsGeneration: 0,
  mapLabelError: null,
};
const worker = new Worker('/lab/assets/preview-worker.js', { type: 'module' });
let previewTimer, toastTimer;
const decisionNames = {
  yes: 'Есть тег',
  no: 'Нет тега',
  unsure: 'Не уверен',
  unreviewed: 'Не размечена',
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').className = error ? 'error' : '';
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => {
      $('toast').hidden = true;
    },
    error ? 10000 : 4500,
  );
}
async function api(path, options = {}) {
  const response = await fetch(
    '/lab/api' + path,
    options.body
      ? {
          ...options,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(options.body),
        }
      : options,
  );
  const value = await response.json();
  if (!response.ok) {
    const detail = value.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join('; ')
          : `Сервис недоступен (${response.status})`,
    );
  }
  return value;
}
const selectedRow = () =>
  state.data?.rows.find((row) => row.analysis_id === state.selected);
const labelValue = (row) => row.label?.value || 'unreviewed';
const groupKey = (row) =>
  row.beatmap_set_id ? `set:${row.beatmap_set_id}` : `input:${row.sha256}`;
const latestEvent = () =>
  Math.max(0, ...(state.data?.rows.map((row) => row.label?.id || 0) || []));
const labelsReady = () => state.mapLabels.has(state.selected);
const currentMapLabels = () => state.mapLabels.get(state.selected) || {};
const formatNumber = (value) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)
    : '—';

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('theme-toggle').textContent = theme === 'dark' ? '☀ Светлая' : '☾ Тёмная';
  $('theme-toggle').setAttribute(
    'aria-label',
    theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему',
  );
  renderHistogram();
}
let savedTheme;
try {
  savedTheme = localStorage.getItem('osu-lab-theme');
} catch {
  /* Storage can be disabled. */
}
setTheme(
  ['light', 'dark'].includes(savedTheme)
    ? savedTheme
    : matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light',
);
$('theme-toggle').onclick = () => {
  const theme =
    document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(theme);
  try {
    localStorage.setItem('osu-lab-theme', theme);
  } catch {
    /* Theme still works for this page. */
  }
};

async function loadMapLabels() {
  const id = state.selected;
  if (!id || state.mapLabels.has(id)) return;
  if (state.labelRequests.has(id)) return state.labelRequests.get(id);
  const generation = state.labelsGeneration;
  state.mapLabelError = null;
  const request = (async () => {
    try {
      const labels = await api(`/analyses/${id}/labels`);
      if (generation !== state.labelsGeneration) return;
      state.mapLabels.set(id, labels);
      const row = state.data?.rows.find((item) => item.analysis_id === id);
      if (row && state.tag) row.label = labels[state.tag.id] || null;
    } catch (error) {
      if (generation !== state.labelsGeneration) return;
      if (id === state.selected) state.mapLabelError = id;
      toast(error.message, true);
    } finally {
      if (generation === state.labelsGeneration) {
        state.labelRequests.delete(id);
        if (id === state.selected) renderAll();
      }
    }
  })();
  state.labelRequests.set(id, request);
  renderSelected();
  return request;
}
function selectMap(id) {
  state.selected = id;
  renderAll();
  loadMapLabels();
}

function renderTags() {
  const list = $('tag-list');
  list.replaceChildren();
  for (const tag of state.tags) {
    const button = element(
      'button',
      undefined,
      'tag-item' + (tag.id === state.tag?.id ? ' active' : ''),
    );
    button.append(element('span', tag.name));
    button.title = tag.description;
    button.disabled = state.saving;
    button.onclick = () => chooseTag(tag);
    list.append(button);
  }
  if (!state.tags.length)
    list.append(
      element(
        'p',
        'Пока нет тегов. Нажмите ＋ и опишите первый паттерн.',
        'tag-empty',
      ),
    );
  $('label-tag-select').replaceChildren(
    ...state.tags.map((tag) => new Option(tag.name, tag.id)),
  );
  $('label-tag-select').value = state.tag?.id || '';
  $('label-tag-select').disabled =
    state.loading || state.saving || !state.tags.length;
}
async function chooseTag(tag) {
  clearTimeout(previewTimer);
  state.tag = tag;
  state.undo = null;
  state.model = null;
  state.data = null;
  state.manual = null;
  state.scores = [];
  state.rules = [];
  state.models = [];
  state.generation++;
  renderSources();
  renderRules();
  $('weights').replaceChildren();
  syncControls();
  renderAll();
  $('tag-title').textContent = tag.name;
  $('tag-description').textContent = tag.description;
  renderTags();
  await loadDataset();
}
async function loadDataset() {
  const generation = ++state.loadGeneration,
    tagId = state.tag?.id;
  state.modelGeneration++;
  state.loading = true;
  syncControls();
  renderSelected();
  renderLearning();
  $('dataset-status').textContent = 'Загружаем сохранённые признаки…';
  try {
    const [data, rules, models] = await Promise.all([
      api('/dataset?limit=1000' + (tagId ? '&tag_id=' + tagId : '')),
      tagId ? api(`/tags/${tagId}/rules`) : [],
      tagId ? api(`/tags/${tagId}/models`) : [],
    ]);
    if (generation !== state.loadGeneration) return;
    state.data = data;
    state.labelsGeneration++;
    state.mapLabels.clear();
    state.labelRequests.clear();
    state.mapLabelError = null;
    state.rules = rules;
    state.models = models;
    state.model = null;
    state.scores = [];
    state.visibleLimit = 200;
    state.undo = null;
    if (!data.rows.some((row) => row.analysis_id === state.selected))
      state.selected = data.rows[0]?.analysis_id ?? null;
    state.manual = {
      weights: Object.fromEntries(
        data.feature_catalog.map((feature) => [feature.key, 0]),
      ),
      bias: 0,
      normalizer: data.normalizer,
    };
    state.threshold = 0.5;
    state.generation++;
    worker.postMessage({ type: 'dataset', rows: data.rows });
    $('dataset-status').textContent =
      `${data.rows.length}${data.truncated ? '+' : ''} карт · ${data.profile.algorithm_version}`;
    $('connection').textContent = 'Библиотека подключена';
    renderSources();
    renderRules();
    renderWeights();
    syncControls();
    renderAll();
    schedulePreview();
  } catch (error) {
    if (generation !== state.loadGeneration) return;
    toast(error.message, true);
    $('connection').textContent = 'Нет соединения';
  } finally {
    if (generation === state.loadGeneration) {
      state.loading = false;
      syncControls();
      renderSelected();
      renderLearning();
      renderMultiTag();
      loadMapLabels();
    }
  }
  if (generation !== state.loadGeneration || !state.data) return;
  const saved = state.rules.find(
    (rule) => rule.specification.profile_sha256 === state.data.profile_sha256,
  );
  if (saved) {
    await loadRule(saved.id);
    if (generation === state.loadGeneration) $('saved-rules').value = saved.id;
  } else if (state.models.length) {
    await selectModel(state.models[0].id);
  }
}
function renderSources() {
  const select = $('scoring-source');
  select.replaceChildren(new Option('Ручное правило', 'manual'));
  for (const [index, model] of state.models.entries()) {
    select.add(
      new Option(
        `Модель ${state.models.length - index} · ${model.train_count} примеров`,
        model.id,
      ),
    );
  }
  select.value = state.model?.id || 'manual';
}
function renderRules() {
  const select = $('saved-rules');
  select.replaceChildren(new Option('Сохранённые версии…', ''));
  for (const rule of state.rules)
    select.add(new Option(rule.specification.name, rule.id));
}
async function selectModel(id) {
  if (state.loading || !state.data) return;
  const generation = ++state.modelGeneration;
  if (id === 'manual') {
    state.model = null;
    syncControls();
    renderAll();
    schedulePreview();
    return;
  }
  const tagId = state.tag?.id;
  try {
    const model = await api(`/models/${id}`);
    if (tagId !== state.tag?.id || generation !== state.modelGeneration) return;
    if (
      Object.entries(state.data.profile).some(
        ([key, value]) => model.artifact.profile[key] !== value,
      )
    ) {
      throw new Error('Эта модель использует другую версию признаков');
    }
    state.model = model;
    renderSources();
    syncControls();
    renderAll();
    schedulePreview();
  } catch (error) {
    if (generation !== state.modelGeneration) return;
    toast(error.message, true);
    $('scoring-source').value = state.model?.id || 'manual';
  }
}
function renderWeights() {
  const fragment = document.createDocumentFragment();
  for (const feature of state.data.feature_catalog) {
    const row = element('div', undefined, 'slider-row'),
      heading = element('div');
    const label = element('label', feature.title),
      output = element('output', '0.00');
    const input = element('input');
    input.type = 'range';
    input.min = '-3';
    input.max = '3';
    input.step = '.05';
    input.id = 'weight-' + feature.key;
    input.value = state.manual.weights[feature.key] || 0;
    label.htmlFor = input.id;
    output.value = Number(input.value).toFixed(2);
    input.oninput = () => {
      state.manual.weights[feature.key] = Number(input.value);
      output.value = Number(input.value).toFixed(2);
      schedulePreview();
    };
    heading.append(label, output);
    row.append(heading, input);
    fragment.append(row);
  }
  $('weights').replaceChildren(fragment);
}
function syncControls() {
  $('threshold').value = state.threshold;
  $('threshold-value').value = state.threshold.toFixed(2);
  $('bias').value = state.manual?.bias || 0;
  $('bias-value').value = (state.manual?.bias || 0).toFixed(2);
  $('manual-controls').hidden = Boolean(state.model);
  $('analytics-panel').hidden = state.mode !== 'rule';
  $('label-panel').hidden = state.mode !== 'label';
  $('label-tag-select').disabled =
    state.loading || state.saving || !state.tags.length;
  $('prediction-mode').textContent =
    state.mode === 'label'
      ? 'Ручные решения'
      : state.model
        ? 'Обученная модель'
        : 'Ручное правило';
  $('save-rule').disabled =
    state.loading || !state.tag || !state.data?.rows.length;
  $('scoring-source').disabled = state.loading || !state.data;
  $('saved-rules').disabled = state.loading || !state.data;
  $('refresh').disabled = state.loading || state.saving;
  const disagree = $('filter').querySelector('[value="disagree"]');
  disagree.disabled = state.mode === 'label';
  for (const value of ['score', 'boundary'])
    $('sort').querySelector(`[value="${value}"]`).disabled =
      state.mode === 'label';
}
function schedulePreview() {
  if (!state.data || !state.manual) return;
  const generation = ++state.generation;
  const specification = structuredClone(state.manual),
    artifact = state.model?.artifact || null;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(
    () =>
      worker.postMessage({
        type: 'evaluate',
        generation,
        specification,
        artifact,
      }),
    35,
  );
}
worker.onmessage = ({ data }) => {
  if (data.generation !== state.generation) return;
  state.scores = data.scores;
  $('preview-time').textContent =
    `Скоринг ${data.elapsed < 1 ? '<1' : data.elapsed.toFixed(1)} ms${data.cacheHit ? ' · кеш' : ''}`;
  renderAll();
};
worker.onerror = () =>
  toast('Предпросмотр не запустился. Обновите страницу.', true);

function displayedRows() {
  if (!state.data) return [];
  const search = $('search').value.trim().toLocaleLowerCase(),
    filter = $('filter').value;
  const rows = state.data.rows
    .map((row, index) => ({ row, score: state.scores[index] ?? null }))
    .filter(({ row, score }) => {
      if (
        search &&
        !`${row.title} ${row.artist} ${row.version}`
          .toLocaleLowerCase()
          .includes(search)
      )
        return false;
      if (filter === 'validation') return row.label?.partition === 'validation';
      if (filter === 'disagree')
        return (
          score !== null &&
          ['yes', 'no'].includes(labelValue(row)) &&
          score >= state.threshold !== (labelValue(row) === 'yes')
        );
      return filter === 'all' || labelValue(row) === filter;
    });
  switch ($('sort').value) {
    case 'score':
      rows.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
      break;
    case 'boundary':
      rows.sort(
        (a, b) =>
          (a.score === null ? Infinity : Math.abs(a.score - state.threshold)) -
          (b.score === null ? Infinity : Math.abs(b.score - state.threshold)),
      );
      break;
    case 'mixed':
      rows.sort(
        (a, b) =>
          ((a.row.input_id * 2654435761) >>> 0) -
          ((b.row.input_id * 2654435761) >>> 0),
      );
      break;
  }
  return rows;
}
function renderTable() {
  const focusedId = document.activeElement?.matches('.map-row')
    ? document.activeElement.dataset.id
    : null;
  const rows = displayedRows(),
    fragment = document.createDocumentFragment();
  for (const { row, score } of rows.slice(0, state.visibleLimit)) {
    const button = element(
      'button',
      undefined,
      'map-row' + (row.analysis_id === state.selected ? ' selected' : ''),
    );
    button.dataset.id = row.analysis_id;
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', row.analysis_id === state.selected);
    button.tabIndex = row.analysis_id === state.selected ? 0 : -1;
    const name = element('span');
    name.append(
      element('span', row.title || 'Без названия', 'map-name'),
      element('span', row.artist || 'Неизвестный артист', 'map-sub'),
    );
    const detail = element('span', undefined, 'map-difficulty');
    detail.append(
      element('span', row.version || 'Без difficulty'),
      element(
        'span',
        decisionNames[labelValue(row)],
        'pill ' + labelValue(row),
      ),
    );
    if (row.label?.partition === 'validation')
      detail.append(element('span', 'К', 'control-mark'));
    name.append(detail);
    const rating = element('span', '★ —', 'map-rating');
    rating.title = 'SR пока не рассчитан';
    if (state.mode === 'rule' && state.tag && score !== null)
      rating.append(element('span', score.toFixed(2), 'score'));
    button.append(element('span', undefined, 'map-symbol'), name, rating);
    button.onclick = () => selectMap(row.analysis_id);
    fragment.append(button);
  }
  if (rows.length > state.visibleLimit) {
    const button = element(
      'button',
      `Показать ещё · ${rows.length - state.visibleLimit} карт`,
      'text-button',
    );
    button.onclick = () => {
      state.visibleLimit += 200;
      renderTable();
    };
    fragment.append(button);
  }
  $('map-list').replaceChildren(fragment);
  if (focusedId)
    document
      .querySelector(`.map-row[data-id="${focusedId}"]`)
      ?.focus({ preventScroll: true });
  $('map-count').textContent = rows.length;
  $('empty').hidden = rows.length > 0;
  $('empty').querySelector('h3').textContent = state.data?.rows.length
    ? 'Нет карт по этому фильтру'
    : 'Здесь появятся ваши карты';
  $('empty').querySelector('p').textContent = state.data?.rows.length
    ? 'Измените поиск или фильтр разметки.'
    : 'Добавьте .osu или дождитесь пакетного анализа.';
}
function renderSelected() {
  const row = selectedRow();
  $('selected-title').textContent = row?.title || 'Выберите карту';
  $('selected-subtitle').textContent = row
    ? `${row.artist} · ${row.version}`
    : 'Ваша библиотека — справа.';
  const stats = document.createDocumentFragment();
  for (const [title, value] of [
    [
      'BPM (red)',
      row
        ? row.features.red_bpm_min === row.features.red_bpm_max
          ? formatNumber(row.features.red_bpm_min)
          : `${formatNumber(row.features.red_bpm_min)}–${formatNumber(row.features.red_bpm_max)}`
        : '—',
    ],
    ['Объекты', row ? formatNumber(row.features.hit_object_count) : '—'],
    ['Слайдеры', row ? formatNumber(row.features.slider_count) : '—'],
    [
      'Размах стартов',
      row ? `${formatNumber(row.features.object_start_span_ms / 1000)} с` : '—',
    ],
  ]) {
    const item = element('div', undefined, 'map-stat');
    item.append(element('span', title), element('strong', value));
    stats.append(item);
  }
  $('map-stats').replaceChildren(stats);
  $('validation').checked = row?.label?.partition === 'validation';
  const disabled =
    !row || !state.tag || state.saving || state.loading || !labelsReady();
  $('validation').disabled = disabled;
  $('clear-label').disabled =
    disabled || labelValue(row || {}) === 'unreviewed';
  $('label-definition').textContent =
    state.tag?.description || 'Создайте тег, чтобы начать разметку.';
  document.querySelectorAll('[data-label]').forEach((button) => {
    button.disabled = disabled;
    button.setAttribute(
      'aria-pressed',
      labelValue(row || {}) === button.dataset.label,
    );
  });
  $('undo').disabled = !state.undo || state.saving || state.loading;
  $('map-link').hidden = !row?.beatmap_id;
  if (row?.beatmap_id)
    $('map-link').href = `https://osu.ppy.sh/beatmaps/${row.beatmap_id}`;
  const values = document.createDocumentFragment();
  for (const feature of state.data?.feature_catalog || []) {
    const value = row?.features[feature.key];
    const entry = element('div', undefined, 'feature-row');
    entry.append(
      element('dt', feature.title),
      element(
        'dd',
        value === null || value === undefined
          ? 'Нет наблюдений'
          : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)} ${feature.unit}`,
      ),
    );
    values.append(entry);
  }
  $('feature-values').replaceChildren(values);
}

function renderMultiTag() {
  const row = selectedRow(),
    labels = currentMapLabels();
  const disabled = !row || state.loading || state.saving || !labelsReady();
  const palette = document.createDocumentFragment(),
    assigned = document.createDocumentFragment(),
    summary = document.createDocumentFragment();
  for (const tag of state.tags) {
    const label = labels[tag.id],
      yes = label?.value === 'yes';
    const chip = element(
      'button',
      undefined,
      'tag-chip' + (yes ? ' assigned' : ''),
    );
    chip.dataset.tagId = tag.id;
    chip.append(element('span', tag.name));
    if (label && label.value !== 'unreviewed')
      chip.append(element('small', decisionNames[label.value]));
    chip.title = tag.description;
    chip.disabled = disabled;
    chip.draggable = !disabled;
    chip.setAttribute('aria-pressed', yes);
    chip.onclick = () => {
      if (!yes) setLabel('yes', label?.partition || 'train', false, tag.id);
    };
    chip.ondragstart = (event) => {
      if (disabled) {
        event.preventDefault();
        return;
      }
      event.dataTransfer.setData('application/x-osu-lab-tag', tag.id);
      event.dataTransfer.effectAllowed = 'copy';
    };
    palette.append(chip);
    if (yes) {
      const item = element('span', undefined, 'assigned-tag');
      const remove = element('button', '×');
      remove.setAttribute('aria-label', `Снять тег «${tag.name}»`);
      remove.disabled = disabled;
      remove.onclick = () =>
        setLabel('unreviewed', label.partition, false, tag.id);
      item.append(element('span', tag.name), remove);
      assigned.append(item);
      summary.append(element('span', tag.name, 'mini-tag'));
    }
  }
  $('tag-palette').replaceChildren(palette);
  $('assigned-tags').replaceChildren(assigned);
  $('selected-tags').replaceChildren(summary);
  $('tag-dropzone').setAttribute('aria-busy', Boolean(row && !labelsReady()));
  $('drop-hint').textContent = !row
    ? 'Выберите карту в библиотеке'
    : state.mapLabelError === state.selected
      ? 'Не удалось прочитать метки. Обновите библиотеку.'
      : !labelsReady()
        ? 'Загружаем ваши метки…'
        : !state.tags.length
          ? 'Создайте первый тег'
          : Object.values(labels).some((label) => label.value === 'yes')
            ? '＋ Ещё один подходящий тег'
            : 'Перетащите сюда подходящие теги';
}

function metricHistogram(key, value) {
  const values = state.data.rows
    .map((row) => row.features[key])
    .filter(Number.isFinite);
  const chart = element('span', undefined, 'mini-histogram');
  chart.setAttribute('role', 'img');
  chart.setAttribute(
    'aria-label',
    `Распределение метрики по ${values.length} картам; эта карта: ${Number.isFinite(value) ? formatNumber(value) : 'нет наблюдения'}`,
  );
  if (!values.length) {
    chart.classList.add('no-marker');
    return chart;
  }
  const min = Math.min(...values),
    max = Math.max(...values),
    span = max - min;
  const bins = Array(14).fill(0);
  for (const value of values)
    bins[span ? Math.min(13, Math.floor(((value - min) / span) * 14)) : 7]++;
  const peak = Math.max(1, ...bins);
  for (const count of bins) {
    const bar = element('i');
    bar.style.height = `${(count / peak) * 100}%`;
    chart.append(bar);
  }
  if (Number.isFinite(value))
    chart.style.setProperty(
      '--marker',
      `${span ? Math.max(0, Math.min(99, ((value - min) / span) * 100)) : 50}%`,
    );
  else chart.classList.add('no-marker');
  return chart;
}

function renderInfluence() {
  const row = selectedRow();
  $('contributions').replaceChildren();
  if (!row || !state.tag || !state.manual) {
    $('selected-score').textContent = '—';
    $('score-verdict').textContent = state.tag
      ? 'Выберите карту'
      : 'Создайте тег';
    $('influence-hint').textContent =
      'Определите скилл и настройте правило на своих примерах.';
    return;
  }
  const explanation = explainScore(
    row.features,
    state.manual,
    state.model?.artifact,
  );
  const score = explanation.score;
  $('selected-score').textContent = score === null ? '—' : score.toFixed(2);
  const configured = Boolean(
    state.model ||
    Object.values(state.manual.weights).some(Boolean) ||
    state.manual.bias,
  );
  $('score-verdict').textContent = !configured
    ? 'Правило пока не настроено'
    : score === null
      ? 'Недостаточно наблюдений'
      : `${score >= state.threshold ? 'Выше' : 'Ниже'} порога ${state.threshold.toFixed(2)}`;
  const terms = [...explanation.terms].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
  );
  const top = terms.slice(0, 6),
    scale = Math.max(0.001, ...top.map((term) => Math.abs(term.contribution)));
  $('influence-hint').textContent =
    score === null
      ? 'Для активной метрики нет наблюдения. Правило не даёт оценку.'
      : !terms.length
        ? `Все веса нулевые: оценка одинакова для всех карт. Смещение: ${explanation.base.toFixed(2)}. Раскройте настройки ниже.`
        : `Смещение: ${explanation.base.toFixed(2)}.${terms.length > 6 ? ` Показаны 6 из ${terms.length} вкладов; остальные входят в оценку.` : ''}`;
  for (const term of top) {
    const feature = state.data.feature_catalog.find(
      (item) => item.key === term.key,
    );
    const entry = element('div', undefined, 'contribution');
    const name = element('span', undefined, 'contribution-name');
    name.append(
      element('span', feature.title),
      element(
        'small',
        term.missing
          ? 'Нет наблюдения · median + missing indicator'
          : `${formatNumber(row.features[term.key])} ${feature.unit}`,
      ),
    );
    const meter = element('span', undefined, 'contribution-meter');
    const bar = element(
      'i',
      undefined,
      'contribution-bar' + (term.contribution < 0 ? ' negative' : ''),
    );
    const width = (Math.abs(term.contribution) / scale) * 48;
    bar.style.width = `${width}%`;
    bar.style.left = `${term.contribution >= 0 ? 50 : 50 - width}%`;
    meter.append(
      bar,
      element(
        'output',
        `${term.contribution >= 0 ? '+' : ''}${term.contribution.toFixed(2)}`,
      ),
    );
    entry.append(
      name,
      metricHistogram(term.key, row.features[term.key]),
      meter,
    );
    $('contributions').append(entry);
  }
}
function renderLearning() {
  const rows = state.data?.rows || [],
    counts = { yes: 0, no: 0, unsure: 0 };
  const controlGroups = new Set(
    rows
      .filter(
        (row) =>
          row.label?.partition === 'validation' &&
          ['yes', 'no'].includes(labelValue(row)),
      )
      .map(groupKey),
  );
  let yes = 0,
    no = 0;
  for (const row of rows) {
    const value = labelValue(row);
    if (value in counts) counts[value]++;
    if (
      row.label?.partition !== 'validation' &&
      !controlGroups.has(groupKey(row))
    ) {
      if (value === 'yes') yes++;
      if (value === 'no') no++;
    }
  }
  $('label-counts').textContent =
    `Есть: ${counts.yes} · Нет: ${counts.no} · Не уверен: ${counts.unsure}`;
  $('training-hint').textContent = state.training
    ? 'Обучение в отдельном CPU-процессе…'
    : `Для обучения: ${yes} «есть» и ${no} «нет». Минимум — по два вне контрольных сетов.`;
  $('train-model').disabled =
    !state.tag || yes < 2 || no < 2 || state.training || state.loading;
  $('train-model').textContent = state.training
    ? 'Модель обучается…'
    : 'Обучить модель';
  const stale = state.model && latestEvent() > state.model.latest_event_id;
  $('model-info').textContent = state.model
    ? `${state.model.train_count} обучающих · ${state.model.validation_count} контрольных · исключено ${state.model.excluded_same_set} карт связанных сетов.${stale ? ' Разметка обновилась — переобучите модель.' : ''}`
    : state.models.length
      ? 'Выберите обученную версию в настройках скилла.'
      : 'Модель ещё не обучена';
  const metrics = confusion(rows, state.scores, state.threshold);
  $('validation-metrics').textContent = stale
    ? 'Контроль изменён после обучения. Метрики появятся после переобучения.'
    : metrics.count
      ? `Контроль для настройки: ${metrics.count} карт. Верно назначен: ${metrics.tp}, лишние назначения: ${metrics.fp}, пропущены: ${metrics.fn}. Точность назначений: ${metrics.precision === null ? '—' : Math.round(metrics.precision * 100) + '%'}, полнота: ${metrics.recall === null ? '—' : Math.round(metrics.recall * 100) + '%'}. Это не итоговая тестовая оценка.`
      : 'Отметьте отдельные контрольные карты для проверки.';
}
function renderHistogram() {
  const canvas = $('histogram'),
    width = canvas.clientWidth,
    height = 60,
    ratio = window.devicePixelRatio || 1;
  if (!width) return;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const bins = new Array(32).fill(0);
  let matching = 0;
  for (const score of state.scores)
    if (score !== null) {
      bins[Math.min(31, Math.floor(score * 32))]++;
      if (score >= state.threshold) matching++;
    }
  const max = Math.max(1, ...bins);
  bins.forEach((count, index) => {
    const colors = getComputedStyle(document.documentElement);
    ctx.fillStyle = colors
      .getPropertyValue(
        (index + 0.5) / 32 >= state.threshold ? '--accent' : '--bar',
      )
      .trim();
    const h = (count / max) * 47;
    ctx.fillRect(
      (index * width) / 32,
      height - h,
      Math.max(1, width / 32 - 2),
      h,
    );
  });
  ctx.fillStyle = getComputedStyle(document.documentElement)
    .getPropertyValue('--text')
    .trim();
  ctx.fillRect(Math.min(width - 1, state.threshold * width), 2, 1, height - 2);
  $('matching').textContent =
    `${matching} карт выше порога ${state.threshold.toFixed(2)}`;
}
function renderAll() {
  renderTable();
  renderSelected();
  renderLearning();
  renderHistogram();
  renderMultiTag();
  renderInfluence();
  $('collection-hint').textContent =
    state.mode === 'label'
      ? `Решения по тегу «${state.tag?.name || '—'}» · ↑ ↓ выбор карты`
      : !state.model &&
          !Object.values(state.manual?.weights || {}).some(Boolean)
        ? 'Все веса нулевые: черновик одинаков для всех карт.'
        : 'Изменения правила пересчитываются по фичам в памяти.';
}
async function setLabel(
  value,
  partition = $('validation').checked ? 'validation' : 'train',
  undo = false,
  tagId = state.tag?.id,
) {
  const row = selectedRow();
  if (!row || !tagId || state.saving || state.loading || !labelsReady()) return;
  const previous = currentMapLabels()[tagId];
  state.saving = true;
  renderSelected();
  renderMultiTag();
  renderTags();
  syncControls();
  if (tagId === state.tag?.id)
    $('validation').checked = partition === 'validation';
  try {
    const label = await api(`/tags/${tagId}/labels`, {
      method: 'POST',
      body: {
        analysis_id: row.analysis_id,
        value,
        partition,
        expected_event_id: previous?.id || null,
      },
    });
    const labels = state.mapLabels.get(row.analysis_id);
    if (labels) labels[tagId] = label;
    if (tagId === state.tag?.id) {
      const current = state.data?.rows.find(
        (item) => item.analysis_id === row.analysis_id,
      );
      if (current) current.label = label;
    }
    state.undo = undo
      ? null
      : {
          tag_id: tagId,
          analysis_id: row.analysis_id,
          expected_event_id: label.id,
          value: previous?.value || 'unreviewed',
          partition: previous?.partition || 'train',
        };
    toast(undo ? 'Решение отменено. История сохранена.' : 'Решение сохранено');
  } catch (error) {
    toast(error.message, true);
    state.mapLabels.delete(row.analysis_id);
    if (state.selected === row.analysis_id) await loadMapLabels();
  } finally {
    state.saving = false;
    renderTags();
    syncControls();
    renderAll();
  }
}
async function trainModel() {
  if (state.training || state.loading || !state.tag) return;
  const tagId = state.tag.id;
  state.training = true;
  renderLearning();
  try {
    const model = await api(`/tags/${tagId}/models`, {
      method: 'POST',
      body: { analysis_ids: state.data.rows.map((row) => row.analysis_id) },
    });
    if (tagId !== state.tag?.id) {
      toast('Модель готова для предыдущего тега');
      return;
    }
    state.models.unshift(model);
    state.model = model;
    setMode('rule');
    renderSources();
    syncControls();
    renderAll();
    schedulePreview();
    toast(
      'Baseline обучен на ручных решениях. Контрольные примеры не участвовали.',
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.training = false;
    renderLearning();
  }
}
async function saveRule() {
  if (state.loading || !state.tag || !state.data) return;
  const tagId = state.tag.id;
  const specification = {
    name: `Версия ${state.rules.length + 1} · ${state.model ? 'порог модели' : 'ручное правило'}`,
    kind: state.model ? 'model' : 'manual',
    threshold: state.threshold,
    bias: state.model ? 0 : state.manual.bias,
    weights: state.model
      ? {}
      : Object.fromEntries(
          Object.entries(state.manual.weights).filter(([, value]) => value),
        ),
    normalizer: state.model ? null : state.manual.normalizer,
    model_id: state.model?.id || null,
    profile_sha256: state.data.profile_sha256,
    dataset_sha256: state.data.dataset_sha256,
  };
  try {
    const rule = await api(`/tags/${tagId}/rules`, {
      method: 'POST',
      body: specification,
    });
    if (tagId === state.tag?.id) {
      state.rules.unshift(rule);
      renderRules();
      $('saved-rules').value = rule.id;
    }
    toast('Новая версия сохранена. Ручная разметка не изменялась.');
  } catch (error) {
    toast(error.message, true);
  }
}
async function loadRule(id) {
  if (state.loading || !state.data) return;
  state.modelGeneration++;
  const rule = state.rules.find((item) => item.id === id)?.specification;
  if (!rule) return;
  if (rule.profile_sha256 !== state.data.profile_sha256) {
    toast('Эта версия использует другие признаки', true);
    return;
  }
  state.threshold = rule.threshold;
  if (rule.kind === 'model') await selectModel(rule.model_id);
  else {
    state.model = null;
    state.manual = {
      weights: {
        ...Object.fromEntries(
          state.data.feature_catalog.map((item) => [item.key, 0]),
        ),
        ...rule.weights,
      },
      bias: rule.bias,
      normalizer: rule.normalizer,
    };
    renderWeights();
    renderSources();
  }
  syncControls();
  renderAll();
  schedulePreview();
}
function setMode(mode) {
  state.mode = mode;
  if (mode === 'label') {
    if (['score', 'boundary'].includes($('sort').value)) $('sort').value = 'id';
    if ($('filter').value === 'disagree') $('filter').value = 'all';
  }
  for (const [key, id] of [
    ['label', 'tab-label'],
    ['rule', 'tab-rule'],
  ]) {
    $(id).classList.toggle('active', mode === key);
    $(id).setAttribute('aria-selected', mode === key);
  }
  syncControls();
  renderAll();
}
$('new-tag').onclick = () => {
  $('tag-dialog').showModal();
  $('tag-name').focus();
};
$('new-tag-label').onclick = $('new-tag').onclick;
$('label-tag-select').onchange = (event) => {
  const tag = state.tags.find((item) => item.id === event.target.value);
  if (tag) chooseTag(tag);
};
$('close-dialog').onclick = () => $('tag-dialog').close();
$('tag-form').onsubmit = async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const tag = await api('/tags', {
      method: 'POST',
      body: {
        name: $('tag-name').value,
        description: $('tag-definition').value,
      },
    });
    state.tags.push(tag);
    $('tag-dialog').close();
    $('tag-form').reset();
    await chooseTag(tag);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
};
$('tab-label').onclick = () => setMode('label');
$('tab-rule').onclick = () => setMode('rule');
$('refresh').onclick = () => loadDataset();
$('scoring-source').onchange = (event) => selectModel(event.target.value);
$('threshold').oninput = (event) => {
  state.threshold = Number(event.target.value);
  $('threshold-value').value = state.threshold.toFixed(2);
  schedulePreview();
};
$('bias').oninput = (event) => {
  if (state.manual) {
    state.manual.bias = Number(event.target.value);
    $('bias-value').value = state.manual.bias.toFixed(2);
    schedulePreview();
  }
};
$('reset-weights').onclick = () => {
  if (state.manual) {
    state.manual.weights = Object.fromEntries(
      state.data.feature_catalog.map((item) => [item.key, 0]),
    );
    state.manual.bias = 0;
    renderWeights();
    syncControls();
    schedulePreview();
  }
};
for (const id of ['search', 'filter', 'sort'])
  $(id).addEventListener(id === 'search' ? 'input' : 'change', () => {
    state.visibleLimit = 200;
    renderTable();
  });
document.querySelectorAll('[data-label]').forEach((button) => {
  button.onclick = () => setLabel(button.dataset.label);
});
$('validation').onchange = () =>
  setLabel(selectedRow()?.label?.value || 'unreviewed');
$('clear-label').onclick = () => setLabel('unreviewed');
$('undo').onclick = async () => {
  if (state.undo) {
    const previous = state.undo;
    selectMap(previous.analysis_id);
    await loadMapLabels();
    if (
      currentMapLabels()[previous.tag_id]?.id !== previous.expected_event_id
    ) {
      state.undo = null;
      renderSelected();
      toast(
        'После этого решения метка уже изменилась. Отмена недоступна.',
        true,
      );
      return;
    }
    setLabel(previous.value, previous.partition, true, previous.tag_id);
  }
};
const dropzone = $('tag-dropzone');
dropzone.ondragover = (event) => {
  if (
    state.mode !== 'label' ||
    !labelsReady() ||
    state.saving ||
    state.loading ||
    !event.dataTransfer.types.includes('application/x-osu-lab-tag')
  )
    return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
  dropzone.classList.add('drag-over');
};
dropzone.ondragleave = (event) => {
  if (!dropzone.contains(event.relatedTarget))
    dropzone.classList.remove('drag-over');
};
document.addEventListener('dragend', () =>
  dropzone.classList.remove('drag-over'),
);
dropzone.ondrop = (event) => {
  event.preventDefault();
  dropzone.classList.remove('drag-over');
  const id = event.dataTransfer.getData('application/x-osu-lab-tag');
  if (
    state.tags.some((tag) => tag.id === id) &&
    currentMapLabels()[id]?.value !== 'yes'
  )
    setLabel('yes', currentMapLabels()[id]?.partition || 'train', false, id);
};
$('train-model').onclick = trainModel;
$('save-rule').onclick = saveRule;
$('saved-rules').onchange = (event) => loadRule(event.target.value);
document.addEventListener('keydown', (event) => {
  if (
    $('tag-dialog').open ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)
  )
    return;
  if (state.mode === 'label' && ['1', '2', '3'].includes(event.key)) {
    event.preventDefault();
    setLabel({ 1: 'yes', 2: 'no', 3: 'unsure' }[event.key]);
  }
  if (['ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault();
    const rows = displayedRows(),
      index = rows.findIndex(({ row }) => row.analysis_id === state.selected);
    const next =
      rows[
        Math.max(
          0,
          Math.min(
            rows.length - 1,
            index + (event.key === 'ArrowDown' ? 1 : -1),
          ),
        )
      ];
    if (next) {
      const mapHadFocus = event.target.closest('.map-row');
      selectMap(next.row.analysis_id);
      const button = document.querySelector(
        `.map-row[data-id="${state.selected}"]`,
      );
      if (mapHadFocus) button?.focus({ preventScroll: true });
      button?.scrollIntoView({ block: 'nearest' });
    }
  }
});
$('upload').onclick = () => $('file-input').click();
$('file-input').onchange = async (event) => {
  const files = [...event.target.files].slice(0, 100);
  if (!files.length) return;
  let succeeded = 0,
    failed = 0;
  $('upload').disabled = true;
  try {
    for (const [index, file] of files.entries()) {
      $('upload').textContent = `Анализ ${index + 1}/${files.length}`;
      try {
        if (
          file.size > 4 * 1024 * 1024 ||
          !file.name.toLowerCase().endsWith('.osu')
        )
          throw new Error('Нужен .osu до 4 MiB');
        const response = await fetch('/analyses', {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: file,
        });
        if (!response.ok) throw new Error(`Ошибка анализа: ${response.status}`);
        succeeded++;
      } catch (error) {
        failed++;
        toast(`${file.name}: ${error.message}`, true);
      }
    }
    await loadDataset();
    toast(
      `Обработано ${succeeded} файлов${failed ? `; ошибок: ${failed}` : ''}`,
    );
  } finally {
    $('upload').disabled = false;
    $('upload').textContent = '＋ .osu';
    event.target.value = '';
  }
};
window.addEventListener('resize', renderHistogram);
try {
  state.tags = await api('/tags');
  renderTags();
  if (state.tags.length) await chooseTag(state.tags[0]);
  else await loadDataset();
} catch (error) {
  toast(error.message, true);
  $('connection').textContent = 'Нет соединения';
}
