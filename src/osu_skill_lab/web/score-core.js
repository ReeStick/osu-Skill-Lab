export function sigmoid(z) {
  if (!Number.isFinite(z)) return null;
  return z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
}

export function scoreManual(features, rule) {
  let z = rule.bias || 0;
  for (const [key, weight] of Object.entries(rule.weights || {})) {
    if (!weight) continue;
    const value = features[key],
      scale = rule.normalizer.scales[key];
    if (
      value === null ||
      value === undefined ||
      !Number.isFinite(scale) ||
      scale <= 0
    )
      return null;
    z += (weight * (value - rule.normalizer.means[key])) / scale;
  }
  return sigmoid(z);
}

export function scoreModel(features, model) {
  const n = model.feature_keys.length;
  let z = model.intercept;
  for (let j = 0; j < n; j++) {
    const key = model.feature_keys[j],
      value = features[key],
      missing = value === null || value === undefined;
    const raw = missing ? model.medians[key] : value;
    z += (model.coefficients[j] * (raw - model.means[key])) / model.scales[key];
    z += model.coefficients[j + n] * Number(missing);
  }
  return sigmoid(z);
}

// Exact additive terms in the linear score, before sigmoid. These are local
// contributions for one map, not causal or global feature importance.
export function explainScore(features, rule, model = null) {
  const base = model ? model.intercept : rule.bias || 0;
  const keys = model ? model.feature_keys : Object.keys(rule.weights || {});
  const terms = [];
  for (const [index, key] of keys.entries()) {
    const weight = model ? model.coefficients[index] : rule.weights[key];
    const missingWeight = model ? model.coefficients[index + keys.length] : 0;
    if (!weight && !missingWeight) continue;
    const raw = features[key];
    const missing = raw === null || raw === undefined;
    if (missing && !model) return { base, terms: [], score: null };
    const value = missing ? model.medians[key] : raw;
    const normalizer = model || rule.normalizer;
    const scale = normalizer.scales[key];
    if (!Number.isFinite(scale) || scale <= 0)
      return { base, terms: [], score: null };
    terms.push({
      key,
      missing,
      contribution:
        (weight * (value - normalizer.means[key])) / scale +
        missingWeight * Number(missing),
    });
  }
  return {
    base,
    terms,
    score: sigmoid(
      base + terms.reduce((sum, term) => sum + term.contribution, 0),
    ),
  };
}

export function confusion(rows, scores, threshold) {
  let tp = 0,
    fp = 0,
    tn = 0,
    fn = 0;
  for (let i = 0; i < rows.length; i++) {
    const label = rows[i].label;
    if (
      label?.partition !== 'validation' ||
      !['yes', 'no'].includes(label.value) ||
      !Number.isFinite(scores[i])
    )
      continue;
    const predicted = scores[i] >= threshold,
      actual = label.value === 'yes';
    if (actual && predicted) tp++;
    else if (!actual && predicted) fp++;
    else if (actual) fn++;
    else tn++;
  }
  return {
    tp,
    fp,
    tn,
    fn,
    count: tp + fp + tn + fn,
    precision: tp + fp ? tp / (tp + fp) : null,
    recall: tp + fn ? tp / (tp + fn) : null,
  };
}

export function evaluate(rows, specification, artifact = null) {
  return rows.map((row) =>
    artifact
      ? scoreModel(row.features, artifact)
      : scoreManual(row.features, specification),
  );
}
