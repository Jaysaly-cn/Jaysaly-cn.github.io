// Run the production workflow functions in a tiny DOM adapter; no model/network.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function element(){return {textContent:'',append(){},replaceChildren(){},className:''};}
function setup(){
 const nodes={};const context=vm.createContext({console,Date,JSON,Map,setTimeout,Blob,URL,localStorage:{setItem(){}},document:{body:{dataset:{project:'evidencebrief'}},querySelector:s=>nodes[s]??=(element()),createElement:element}});
 const code=fs.readFileSync(__dirname+'/demo.js','utf8').replace(/start\(\)\.catch\(e=>message\(e.message\)\);\s*$/,'');
 vm.runInContext(code,context);
 vm.runInContext('config={source:"原文资料",candidates:[]};state=initial();',context);
 return code=>vm.runInContext(code,context);
}
test('unreviewed content cannot become a delivery',()=>{const run=setup();run('addRecord("判断","原文");');assert.throws(()=>run('freeze()'),/确认至少一条/);assert.equal(run('state.snapshots.length'),0);});
test('only approved records are included',()=>{const run=setup();run('addRecord("确认内容","原文");addRecord("待核对","原文");addRecord("拒绝内容","原文");state.records[0].status="approved";state.records[2].status="rejected";freeze();');assert.equal(run('state.snapshots[0].records.length'),1);assert.equal(run('state.snapshots[0].records[0].text'),'确认内容');});
test('frozen content is independent of later edits and source changes',()=>{const run=setup();run('addRecord("旧判断","原文");state.records[0].status="approved";freeze();state.records[0].text="新判断";state.source="新原文";');assert.equal(run('state.snapshots[0].records[0].text'),'旧判断');assert.equal(run('state.snapshots[0].source'),'原文资料');});
test('exports explicitly identify the non-model synthetic demo',()=>{const run=setup();run('addRecord("判断","原文");state.records[0].status="approved";freeze();');assert.equal(run('state.snapshots[0].synthetic'),true);assert.equal(run('state.snapshots[0].model_called'),false);assert.equal(run('state.snapshots[0].mode'),'browser-demo');});
test('storage denial does not lose current in-memory workflow',()=>{const run=setup();run('localStorage.setItem=()=>{throw Error("denied")};addRecord("判断","原文");state.records[0].status="approved";freeze();');assert.equal(run('state.snapshots.length'),1);});
test('snapshot quota is enforced before mutation',()=>{const run=setup();run('addRecord("判断","原文");state.records[0].status="approved";for(let i=0;i<20;i++)freeze();');assert.throws(()=>run('freeze()'),/20/);assert.equal(run('state.snapshots.length'),20);});
test('all eleven demo fixtures are reachable and quotes belong to their sources',()=>{const catalogue=JSON.parse(fs.readFileSync(__dirname+'/../../ai/projects.json','utf8'));assert.equal(catalogue.length,11);for(const p of catalogue){const data=JSON.parse(fs.readFileSync(__dirname+'/'+p.id+'.json','utf8'));assert.equal(data.id,p.id);for(const c of data.candidates)assert.ok(data.source.includes(c.quote),p.id);const html=fs.readFileSync(__dirname+'/'+p.id+'.html','utf8');assert.ok(html.includes('不调用大模型'));assert.ok(!html.includes('trycloudflare'));assert.ok(fs.statSync(__dirname+'/../../assets/ai-covers/'+p.id+'.png').size>10000);}});
