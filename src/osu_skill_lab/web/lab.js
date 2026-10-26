import { confusion } from './score-core.js';

const $ = (id) => document.getElementById(id);
const state = {
  tags: [],
  tag: null,
  data: null,
  selected: null,
  scores: [],
  mode: 'label',
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
const selectedRow = () => state.data?.rows.find((row) => row.analysis_id === state.selected);
const labelValue = (row) => row.label?.value || 'unreviewed';
const groupKey = (row) =>
  row.beatmap_set_id ? `set:${row.beatmap_set_id}` : `input:${row.sha256}`;
const latestEvent = () => Math.max(0, ...(state.data?.rows.map((row) => row.label?.id || 0) || []));

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
    button.onclick = () => chooseTag(tag);
    list.append(button);
  }
  if (!state.tags.length)
    list.append(element('p', 'Пока нет тегов. Нажмите ＋ и опишите первый паттерн.', 'tag-empty'));
}
async function chooseTag(tag) {
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
    state.rules = rules;
    state.models = models;
    state.model = null;
    state.scores = [];
    state.visibleLimit = 200;
    state.undo = null;
    if (!data.rows.some((row) => row.analysis_id === state.selected))
      state.selected = data.rows[0]?.analysis_id ?? null;
    state.manual = {
      weights: Object.fromEntries(data.feature_catalog.map((feature) => [feature.key, 0])),
      bias: 0,
      normalizer: data.normalizer,
    };
    state.threshold = 0.5;
    state.generation++;
    worker.postMessage({ type: 'dataset', rows: data.rows });
    $('dataset-status').textContent =
      `${data.rows.length}${data.truncated ? '+' : ''} карт · ${data.profile.algorithm_version} · фичи в памяти`;
    $('connection').textContent = 'Сохранено в PostgreSQL';
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
    }
  }
}
function renderSources() {
  const select = $('scoring-source');
  select.replaceChildren(new Option('Ручное правило', 'manual'));
  for (const [index, model] of state.models.entries()) {
    select.add(
      new Option(`Модель ${state.models.length - index} · ${model.train_count} примеров`, model.id),
    );
  }
  select.value = state.model?.id || 'manual';
}
function renderRules() {
  const select = $('saved-rules');
  select.replaceChildren(new Option('Сохранённые версии…', ''));
  for (const rule of state.rules) select.add(new Option(rule.specification.name, rule.id));
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
  $('rule-panel').hidden = state.mode !== 'rule';
  $('score-strip').hidden = state.mode !== 'rule';
  $('feature-panel').hidden = state.mode === 'rule';
  $('prediction-mode').textContent =
    state.mode === 'label'
      ? 'Ручные решения'
      : state.model
        ? 'Обученная модель'
        : 'Черновик правила';
  $('save-rule').disabled = state.loading || !state.tag || !state.data?.rows.length;
  $('scoring-source').disabled = state.loading || !state.data;
  $('saved-rules').disabled = state.loading || !state.data;
}
function schedulePreview() {
  if (!state.data || !state.manual) return;
  const generation = ++state.generation;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(
    () =>
      worker.postMessage({
        type: 'evaluate',
        generation,
        specification: state.manual,
        artifact: state.model?.artifact || null,
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
worker.onerror = () => toast('Предпросмотр не запустился. Обновите страницу.', true);

function displayedRows() {
  if (!state.data) return [];
  const search = $('search').value.trim().toLocaleLowerCase(),
    filter = $('filter').value;
  const rows = state.data.rows
    .map((row, index) => ({ row, score: state.scores[index] ?? null }))
    .filter(({ row, score }) => {
      if (
        search &&
        !`${row.title} ${row.artist} ${row.version}`.toLocaleLowerCase().includes(search)
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
        (a, b) => ((a.row.input_id * 2654435761) >>> 0) - ((b.row.input_id * 2654435761) >>> 0),
      );
      break;
  }
  return rows;
}
function renderTable() {
  const rows = displayedRows(),
    fragment = document.createDocumentFragment();
  for (const { row, score } of rows.slice(0, state.visibleLimit)) {
    const tr = element(
      'tr',
      undefined,
      'map-row' + (row.analysis_id === state.selected ? ' selected' : ''),
    );
    tr.dataset.id = row.analysis_id;
    tr.tabIndex = 0;
    tr.setAttribute('aria-selected', row.analysis_id === state.selected);
    const name = element('td');
    name.append(
      element('span', row.title || 'Без названия', 'map-name'),
      element('span', `${row.artist} · ${row.version}`, 'map-sub'),
    );
    const label = element('td');
    label.append(element('span', decisionNames[labelValue(row)], 'pill ' + labelValue(row)));
    if (row.label?.partition === 'validation') label.append(element('span', 'К', 'control-mark'));
    const output = element(
      'td',
      state.mode === 'rule' && score !== null ? score.toFixed(2) : '—',
      'score' + (score !== null && score >= state.threshold ? ' passes' : ''),
    );
    tr.append(name, label, output);
    tr.onclick = () => {
      state.selected = row.analysis_id;
      renderAll();
    };
    tr.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        tr.click();
      }
    };
    fragment.append(tr);
  }
  if (rows.length > state.visibleLimit) {
    const tr = element('tr'),
      td = element('td'),
      button = element(
        'button',
        `Показать ещё · ${rows.length - state.visibleLimit} карт`,
        'text-button',
      );
    td.colSpan = 3;
    button.onclick = () => {
      state.visibleLimit += 200;
      renderTable();
    };
    td.append(button);
    tr.append(td);
    fragment.append(tr);
  }
  $('map-list').replaceChildren(fragment);
  $('map-count').textContent = rows.length;
  $('empty').hidden = rows.length > 0;
  if (state.data?.rows.length && !rows.length) {
    $('empty').querySelector('h3').textContent = 'Нет карт по этому фильтру';
    $('empty').querySelector('p').textContent = 'Измените поисковый запрос или состояние разметки.';
  } else {
    $('empty').querySelector('h3').textContent = 'Здесь появятся ваши карты';
    $('empty').querySelector('p').textContent =
      'Загрузите .osu или дождитесь завершения пакетного анализа.';
  }
}
function renderSelected() {
  const row = selectedRow();
  $('selected-title').textContent = row ? `${row.title} [${row.version}]` : 'Выберите карту';
  $('validation').checked = row?.label?.partition === 'validation';
  $('validation').disabled = !row || !state.tag || state.saving || state.loading;
  document.querySelectorAll('[data-label]').forEach((button) => {
    button.disabled = !row || !state.tag || state.saving || state.loading;
  });
  $('undo').disabled = !state.undo || state.saving;
  $('map-link').hidden = !row?.beatmap_id;
  if (row?.beatmap_id) $('map-link').href = `https://osu.ppy.sh/beatmaps/${row.beatmap_id}`;
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
function renderLearning() {
  const rows = state.data?.rows || [],
    counts = { yes: 0, no: 0, unsure: 0 };
  const controlGroups = new Set(
    rows
      .filter(
        (row) => row.label?.partition === 'validation' && ['yes', 'no'].includes(labelValue(row)),
      )
      .map(groupKey),
  );
  let yes = 0,
    no = 0;
  for (const row of rows) {
    const value = labelValue(row);
    if (value in counts) counts[value]++;
    if (row.label?.partition !== 'validation' && !controlGroups.has(groupKey(row))) {
      if (value === 'yes') yes++;
      if (value === 'no') no++;
    }
  }
  $('label-counts').textContent =
    `Есть: ${counts.yes} · Нет: ${counts.no} · Не уверен: ${counts.unsure}`;
  $('training-hint').textContent = state.training
    ? 'Обучение в отдельном CPU-процессе…'
    : `Для обучения: ${yes} «есть» и ${no} «нет». Минимум — по два вне контрольных сетов.`;
  $('train-model').disabled = !state.tag || yes < 2 || no < 2 || state.training || state.loading;
  $('train-model').textContent = state.training ? 'Модель обучается…' : 'Обучить модель';
  const stale = state.model && latestEvent() > state.model.latest_event_id;
  $('model-info').textContent = state.model
    ? `${state.model.train_count} обучающих · ${state.model.validation_count} контрольных · исключено ${state.model.excluded_same_set} карт связанных сетов.${stale ? ' Разметка обновилась — переобучите модель.' : ''}`
    : state.models.length
      ? 'Выберите обученную версию в режиме «Правило и модель».'
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
    ctx.fillStyle = (index + 0.5) / 32 >= state.threshold ? '#b59be7' : '#383342';
    const h = (count / max) * 47;
    ctx.fillRect((index * width) / 32, height - h, Math.max(1, width / 32 - 2), h);
  });
  ctx.fillStyle = '#eadbff';
  ctx.fillRect(Math.min(width - 1, state.threshold * width), 2, 1, height - 2);
  $('matching').textContent = `${matching} карт`;
}
function renderAll() {
  renderTable();
  renderSelected();
  renderLearning();
  renderHistogram();
  $('collection-hint').textContent =
    state.mode === 'label'
      ? 'Решения человека сохраняются отдельно от прогнозов.'
      : !state.model && !Object.values(state.manual?.weights || {}).some(Boolean)
        ? 'Все веса нулевые: черновик одинаков для всех карт.'
        : 'Изменения правила пересчитываются по фичам в памяти.';
}
async function setLabel(
  value,
  partition = $('validation').checked ? 'validation' : 'train',
  undo = false,
) {
  const row = selectedRow(),
    tagId = state.tag?.id;
  if (!row || !tagId || state.saving || state.loading) return;
  const previous = row.label;
  state.saving = true;
  renderSelected();
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
    row.label = label;
    if (tagId === state.tag?.id)
      state.undo = undo
        ? null
        : {
            analysis_id: row.analysis_id,
            value: previous?.value || 'unreviewed',
            partition: previous?.partition || 'train',
          };
    toast(undo ? 'Решение отменено. История сохранена.' : 'Решение сохранено');
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.saving = false;
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
    toast('Baseline обучен на ручных решениях. Контрольные примеры не участвовали.');
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
      : Object.fromEntries(Object.entries(state.manual.weights).filter(([, value]) => value)),
    normalizer: state.model ? null : state.manual.normalizer,
    model_id: state.model?.id || null,
    profile_sha256: state.data.profile_sha256,
    dataset_sha256: state.data.dataset_sha256,
  };
  try {
    const rule = await api(`/tags/${tagId}/rules`, { method: 'POST', body: specification });
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
        ...Object.fromEntries(state.data.feature_catalog.map((item) => [item.key, 0])),
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
$('close-dialog').onclick = () => $('tag-dialog').close();
$('tag-form').onsubmit = async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const tag = await api('/tags', {
      method: 'POST',
      body: { name: $('tag-name').value, description: $('tag-definition').value },
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
$('validation').onchange = () => setLabel(selectedRow()?.label?.value || 'unreviewed');
$('undo').onclick = () => {
  if (state.undo) {
    const previous = state.undo;
    state.selected = previous.analysis_id;
    setLabel(previous.value, previous.partition, true);
  }
};
$('train-model').onclick = trainModel;
$('save-rule').onclick = saveRule;
$('saved-rules').onchange = (event) => loadRule(event.target.value);
document.addEventListener('keydown', (event) => {
  if ($('tag-dialog').open || ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName))
    return;
  if (['1', '2', '3'].includes(event.key)) {
    event.preventDefault();
    setLabel({ 1: 'yes', 2: 'no', 3: 'unsure' }[event.key]);
  }
  if (['ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault();
    const rows = displayedRows(),
      index = rows.findIndex(({ row }) => row.analysis_id === state.selected);
    const next =
      rows[Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))];
    if (next) {
      state.selected = next.row.analysis_id;
      renderAll();
      document
        .querySelector(`tr[data-id="${state.selected}"]`)
        ?.scrollIntoView({ block: 'nearest' });
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
        if (file.size > 4 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.osu'))
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
    toast(`Обработано ${succeeded} файлов${failed ? `; ошибок: ${failed}` : ''}`);
  } finally {
    $('upload').disabled = false;
    $('upload').textContent = '＋ Добавить .osu';
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
