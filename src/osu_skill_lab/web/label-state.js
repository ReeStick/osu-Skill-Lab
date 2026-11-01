// Explicit human decisions only. Predictions never enter this module.
export function automaticPartition(row) {
  const group = row.beatmap_set_id
    ? `set:${row.beatmap_set_id}`
    : `input:${row.sha256}`;
  let hash = 2166136261;
  for (const character of group)
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  return hash % 5 === 0 ? "validation" : "train";
}
export function decisionBody(row, previous, value) {
  return {
    analysis_id: row.analysis_id,
    value,
    partition: previous?.partition ?? automaticPartition(row),
    expected_event_id: previous?.id ?? null,
  };
}
export function undoBody(action) {
  return {
    analysis_id: action.row.analysis_id,
    value: action.previous?.value ?? "unreviewed",
    partition: action.previous?.partition ?? action.saved.partition,
    expected_event_id: action.saved.id,
  };
}
export const labelName = (value) =>
  ({
    yes: "есть",
    no: "нет",
    unsure: "не уверен",
    unreviewed: "ещё не оценено",
  })[value] ?? "ещё не оценено";
