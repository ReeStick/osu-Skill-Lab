import test from 'node:test';
import assert from 'node:assert/strict';
import {
  confusion,
  evaluate,
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
  assert.deepEqual(evaluate([{ features: { x: null } }], {}, artifact), [sigmoid(1.5)]);
});
test('control metrics never treat missing scores, unsure or unreviewed as negatives', () => {
  const row = (value, partition = 'validation') => ({ label: { value, partition } });
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
