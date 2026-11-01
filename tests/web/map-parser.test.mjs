import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  parseOsu,
  fitPath,
  pointAt,
} from "../../src/osu_skill_lab/web/map-parser.js";
const make = (objects, timing = "0,500,4,1,0,100,1,0", diff = "") =>
  `osu file format v14\n[General]\nMode:0\n[Difficulty]\nSliderMultiplier:1\n${diff}\n[TimingPoints]\n${timing}\n[HitObjects]\n${objects}`;
test("reads the shared analytical fixture and preserves time ordering", () => {
  const map = parseOsu(
    readFileSync(
      new URL("../fixtures/analytic-v14.osu", import.meta.url),
      "utf8",
    ),
  );
  assert(map.objects.length > 0);
  assert(map.objects.some((o) => o.kind === "slider"));
  assert(map.objects.every((o, i, a) => i === 0 || o.t >= a[i - 1].t));
});
test("red timing resets SV; inherited timing and repeats determine duration", () => {
  const map = parseOsu(
    make(
      "0,0,1000,2,0,L|200:0,2,200\n0,0,2000,2,0,L|200:0,1,200",
      "0,500,4,1,0,100,1,0\n500,-50,4,1,0,100,0,0\n1500,400,4,1,0,100,1,0",
    ),
  );
  assert.equal(map.objects[0].span, 500);
  assert.equal(map.objects[0].end, 2000);
  assert.equal(map.objects[1].span, 800);
});
test("arc and repeated-anchor Bezier paths are finite and trimmed to expected length", () => {
  for (const path of [
    "P|100:100|200:0",
    "B|100:0|100:0|100:100",
    "C|100:100|200:0",
  ]) {
    const o = parseOsu(make(`0,0,1000,2,0,${path},1,150`)).objects[0];
    assert.equal(o.path.length, 150);
    assert(o.path.points.flat().every(Number.isFinite));
  }
  const path = fitPath(
    [
      [0, 0],
      [200, 0],
    ],
    100,
  );
  assert.deepEqual(pointAt(path, 0.5), [50, 0]);
  assert.deepEqual(pointAt(path, 1), [100, 0]);
});
test("rejects malformed and unsupported maps before rendering", () => {
  assert.throws(() => parseOsu("bad"));
  assert.throws(() =>
    parseOsu(make("0,0,1000,1,0").replace("Mode:0", "Mode:3")),
  );
  assert.throws(() => parseOsu(make("0,0,1000,2,0,L|20:0,NaN,100")));
  assert.throws(() => parseOsu(make("0,0,1000,8,0,900")));
  assert.throws(() => parseOsu(make("NaN,0,1000,1,0")));
});
