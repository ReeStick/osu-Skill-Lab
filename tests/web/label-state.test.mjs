import test from "node:test";
import assert from "node:assert/strict";
import {
  automaticPartition,
  decisionBody,
  undoBody,
} from "../../src/osu_skill_lab/web/label-state.js";
const row = { analysis_id: 5, beatmap_set_id: 12, sha256: "a".repeat(64) };
test("collection toggle removal is unreviewed, not an implicit negative", () => {
  const prior = { id: 7, value: "yes", partition: "validation" };
  assert.deepEqual(decisionBody(row, prior, "unreviewed"), {
    analysis_id: 5,
    value: "unreviewed",
    partition: "validation",
    expected_event_id: 7,
  });
});
test("new decisions group difficulties automatically without moving existing labels", () => {
  assert.equal(
    automaticPartition(row),
    automaticPartition({ ...row, analysis_id: 8, sha256: "b".repeat(64) }),
  );
  assert.equal(
    decisionBody(row, { id: 8, partition: "train" }, "yes").partition,
    "train",
  );
  assert.equal(decisionBody(row, null, "unsure").expected_event_id, null);
  assert.equal(decisionBody(row, null, "unsure").value, "unsure");
});
test("undo fences the event actually saved, including cross-map undo", () => {
  const saved = { id: 20, partition: "train" };
  assert.deepEqual(undoBody({ row, previous: null, saved }), {
    analysis_id: 5,
    value: "unreviewed",
    partition: "train",
    expected_event_id: 20,
  });
  assert.equal(
    undoBody({
      row,
      previous: { id: 1, value: "no", partition: "validation" },
      saved,
    }).value,
    "no",
  );
});
