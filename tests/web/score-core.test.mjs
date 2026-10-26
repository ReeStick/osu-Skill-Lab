import test from 'node:test';
import assert from 'node:assert/strict';
import {
  confusion,
  evaluate,
  explainScore,
  scoreManual,
  scoreModel,
  sigmoid,
} from '../../src/osu_skill_lab/web/score-core.js';

test('manual scoring handles missing values only for active weights', () => {
  const rule = {
    weights: { x: 2, y: 0 },
    bias: 0,
    normalizer: { means: { x: 10, y: 0 }, scales: { x: 2, y: 1 } },
  };
  assert.equal(scoreManual({ x: 12, y: null }, rule), sigmoid(2));
  assert.equal(scoreManual({ x: null }, rule), null);
  assert.equal(scoreManual({ x: 12 }, { ...rule, weights: {} }), 0.5);
  assert.equal(sigmoid(1000), 1);
  assert.equal(sigmoid(-1000), 0);
});
test('portable model uses standardized numeric then missing-indicator coefficients', () => {
  const artifact = {
    feature_keys: ['x'],
    medians: { x: 10 },
    means: { x: 8 },
    scales: { x: 2 },
    coefficients: [2, -1],
    intercept: 0.5,
  };
  assert.equal(scoreModel({ x: null }, artifact), sigmoid(1.5));
  assert.equal(scoreModel({ x: 10 }, artifact), sigmoid(2.5));
  assert.deepEqual(evaluate([{ features: { x: null } }], {}, artifact), [
    sigmoid(1.5),
  ]);
});
test('control metrics never treat missing scores, unsure or unreviewed as negatives', () => {
  const row = (value, partition = 'validation') => ({
    label: { value, partition },
  });
  const rows = [
    row('yes'),
    row('no'),
    row('unsure'),
    row('yes', 'train'),
    row('no'),
    row('yes'),
    row('no'),
  ];
  const scores = [0.9, 0.8, 0.1, 0.9, null, 0.2];
  assert.deepEqual(confusion(rows, scores, 0.5), {
    tp: 1,
    fp: 1,
    tn: 0,
    fn: 1,
    count: 3,
    precision: 0.5,
    recall: 0.5,
  });
  assert.equal(confusion(rows, scores, 0.95).precision, null);
});

test('local contributions reconstruct manual scores including negative effects and missing input', () => {
  const rule = {
    bias: -0.5,
    weights: { x: 2, y: -1 },
    normalizer: { means: { x: 10, y: 2 }, scales: { x: 2, y: 1 } },
  };
  const features = { x: 12, y: 5 };
  const result = explainScore(features, rule);
  assert.deepEqual(
    result.terms.map((term) => term.contribution),
    [2, -3],
  );
  assert.equal(result.base, -0.5);
  assert.equal(result.score, scoreManual(features, rule));
  assert.equal(explainScore({ x: null, y: 5 }, rule).score, null);
  assert.equal(explainScore({}, { bias: 1, weights: {} }).score, sigmoid(1));
});

test('model explanation includes imputation and missing indicators without inventing an observation', () => {
  const model = {
    feature_keys: ['x', 'y'],
    medians: { x: 10, y: 3 },
    means: { x: 8, y: 1 },
    scales: { x: 2, y: 2 },
    coefficients: [2, -3, -1, 4],
    intercept: 0.5,
  };
  for (const features of [
    { x: null, y: 3 },
    { x: 10, y: null },
    { x: 0, y: 5 },
  ]) {
    const result = explainScore(features, {}, model);
    assert.ok(Math.abs(result.score - scoreModel(features, model)) < 1e-12);
    assert.equal(result.terms[0].missing, features.x === null);
  }
  assert.equal(
    explainScore({ x: null, y: 3 }, {}, model).terms[0].contribution,
    1,
  );
});
