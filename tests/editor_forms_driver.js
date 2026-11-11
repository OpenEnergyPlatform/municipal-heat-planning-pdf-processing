// Driver of tests/test_editor_forms.py: runs the pure form functions of
// docpipe/editor/web/forms.js on the jobs it reads from stdin (a JSON list),
// writes the answers as a JSON list. `broken` names a deliberate defect the
// test uses to show that its checks can fail.
'use strict';
const path = require('path');
const F = require(path.join(__dirname, '..', 'docpipe', 'editor', 'web', 'forms.js'));

function specOf(recipe) {
  switch (recipe.recipe) {
    case 'kg': return F.recordOf(recipe.decls);
    case 'rule': return F.ruleSpec(recipe.rule);
    case 'example': return F.exampleSpec(F.exampleColumns(recipe.coordinates, recipe.value),
      F.defaultKeysOf(recipe.coordinates, recipe.value), recipe.numeric);
    case 'derive': return { k: 'record', fields: [{ key: 'from', kind: F.TEXT }, { key: 'value', kind: F.TEXT }] };
    case 'entry_of': return { k: 'map', value: F.TEXT };
  }
  throw new Error('no recipe ' + recipe.recipe);
}

// A converter that breaks the promise on purpose.
function spoil(kind, value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(v => spoil(kind, v));
  const keys = Object.keys(value);
  if (kind === 'drop_unknown') { const out = {}; for (const k of keys.slice(0, -1)) out[k] = spoil(kind, value[k]); return out; }
  if (kind === 'reorder') { const out = {}; for (const k of keys.slice().reverse()) out[k] = spoil(kind, value[k]); return out; }
  if (kind === 'drop_empty') { const out = {}; for (const k of keys) if (value[k] !== '' && value[k] !== null) out[k] = spoil(kind, value[k]); return out; }
  return value;
}

const jobs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const answers = jobs.map(job => {
  const spec = specOf(job.recipe);
  const st = F.stateOf(spec, job.value);
  const give = v => job.broken ? spoil(job.broken, v) : v;
  if (job.op === 'roundtrip') return { value: give(F.valueOf(st)) };
  if (job.op === 'leaves') return { leaves: F.leaves(st) };
  if (job.op === 'edit') { F.edit(st, job.path, job.text); return { value: give(F.valueOf(st)) }; }
  if (job.op === 'add_row') { const i = F.addRow(st, job.path); return { index: i, value: F.valueOf(st) }; }
  if (job.op === 'add_pair') { const i = F.addPair(st, job.path); return { index: i, value: F.valueOf(st) }; }
  throw new Error('no op ' + job.op);
});
process.stdout.write(JSON.stringify(answers));
