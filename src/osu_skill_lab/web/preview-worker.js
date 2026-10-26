import { evaluate } from './score-core.js';
let rows = [];
let cachedKey = null,
  cachedScores = [];
self.onmessage = ({ data }) => {
  if (data.type === 'dataset') {
    rows = data.rows;
    cachedKey = null;
    return;
  }
  const start = performance.now();
  // Threshold is deliberately absent: changing it reuses scores.
  const key = JSON.stringify([
    data.specification.weights,
    data.specification.bias,
    data.specification.normalizer,
    data.artifact,
  ]);
  const cacheHit = key === cachedKey;
  if (!cacheHit) {
    cachedScores = evaluate(rows, data.specification, data.artifact);
    cachedKey = key;
  }
  self.postMessage({
    generation: data.generation,
    scores: cachedScores,
    elapsed: performance.now() - start,
    cacheHit,
  });
};
