import { scoreModel } from '../../src/osu_skill_lab/web/score-core.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { artifact, features } = JSON.parse(input);
process.stdout.write(JSON.stringify(features.map((row) => scoreModel(row, artifact))));
