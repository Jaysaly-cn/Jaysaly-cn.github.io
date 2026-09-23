// Offline assertion replay, using the same pinned engine as live evaluations.
process.env.PROMPTFOO_DISABLE_TELEMETRY = '1';
process.env.PROMPTFOO_DISABLE_UPDATE = '1';
process.env.PROMPTFOO_DISABLE_REMOTE_GENERATION = 'true';
const fs = await import('node:fs/promises');
const {assertions} = await import('promptfoo');
const input = JSON.parse(await fs.readFile(new URL('../data/schema-probe-input.json', import.meta.url), 'utf8'));
const pkg = JSON.parse(await fs.readFile(new URL('../node_modules/promptfoo/package.json', import.meta.url), 'utf8'));
if (pkg.version !== '0.123.1') throw Error('Pinned engine required');
const rows = [];
for (const row of input.rows) {
  const options = {test: {}, providerResponse: {output: row.output}};
  const syntax = await assertions.runAssertion({...options, assertion: {type:'is-json'}});
  const structure = await assertions.runAssertion({...options, assertion: {type:'is-json', value: input.schemas[row.profile]}});
  if (row.expected !== undefined && structure.pass !== row.expected) throw Error('Unexpected validation: '+row.id);
  rows.push({...row, syntax: {pass:syntax.pass, reason:syntax.reason}, structure: {pass:structure.pass, reason:structure.reason}});
}
const output = {scope:'Offline replay of unchanged model output plus synthetic boundary fixtures; zero new model calls', engine:pkg.version, schemas:input.schemas, rows};
await fs.writeFile(new URL('../artifacts/schema-probe.json',import.meta.url), JSON.stringify(output,null,2));
console.log(JSON.stringify({rows:rows.length,fixtures:rows.filter(r=>r.expected!==undefined).length,newlyRejected:rows.filter(r=>r.run_id && r.syntax.pass&&!r.structure.pass).map(r=>r.id)}));
