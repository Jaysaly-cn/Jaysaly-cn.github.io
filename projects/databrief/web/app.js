'use strict';
const $=s=>document.querySelector(s),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
let selected=null,proposalId=null,shown=null,sequence=0,configured=false;
function notice(text,error=false){$('#notice').textContent=text;$('#notice').className=error?'error':'';}
async function api(path,data,raw=false){const headers={Authorization:'Bearer '+(sessionStorage.getItem('dbr-token')||'')};if(data!==undefined)headers['Content-Type']=raw?'text/csv':'application/json';const r=await fetch('/api'+path,{method:data===undefined?'GET':'POST',headers,body:data===undefined?undefined:raw?data:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'请检查输入格式与长度');return result;}
function action(button,fn){button.addEventListener('click',async()=>{button.disabled=true;try{await fn();}catch(e){notice(e.message,true);}finally{button.disabled=false;}});}
function button(text,fn){const b=el('button',text);b.type='button';b.className='quiet';action(b,fn);return b;}
function table(target,columns,rows){const t=el('table'),head=el('thead'),hr=el('tr'),body=el('tbody');columns.forEach(c=>{const th=el('th',c);th.scope='col';hr.append(th);});head.append(hr);rows.forEach(row=>{const tr=el('tr');row.forEach(value=>tr.append(el('td',value===null?'NULL':String(value))));body.append(tr);});t.append(head,body);target.replaceChildren(t);}
async function list(){const rows=await api('/datasets');$('#datasets').replaceChildren(...rows.map(r=>{const b=button(r.name,()=>load(r.id));if(r.id===selected?.id)b.className='active';return b;}));}
function useProposal(p){proposalId=p.id;$('#question').value=p.question;$('#sql').value=p.sql;$('#reviewed').checked=false;$('#review-note').value='';$('#proposal-note').textContent=`模型说明：${p.explanation}\n局限：${p.limitations}\n仅为模型提议，需核对。`;}
async function histories(id){const [proposals,runs]=await Promise.all([api(`/datasets/${id}/proposals`),api(`/datasets/${id}/runs`)]);if(selected?.id!==id)return;$('#proposals').replaceChildren(...proposals.map(p=>{const d=el('details');d.append(el('summary',`${p.state==='proposed'?'待核对提议':'协议失败'} · ${p.question}`),el('pre',p.raw||p.error));if(p.state==='proposed')d.append(button('载入编辑区',()=>useProposal({id:p.id,question:p.question,...p.proposal})));return d;}));$('#history').replaceChildren(...runs.map(r=>button(`${new Date(r.created_at).toLocaleString()} · ${r.result.state==='succeeded'?'成功':'失败'}`,()=>display(r))));if(!runs.length)$('#history').append(el('p','尚无执行记录。生成提议不会自动执行。'));}
async function load(id){const ticket=++sequence;const source=await api('/datasets/'+id);if(ticket!==sequence)return;selected=source;proposalId=null;shown=null;$('#welcome').hidden=true;$('#study').hidden=false;$('#result-panel').hidden=true;$('#name').textContent=source.name;$('#stats').textContent=`${source.row_count} 行 · ${source.columns.length} 列`;$('#source-note').textContent=source.notice;$('#hash').textContent='原始 CSV SHA-256：'+source.sha256;table($('#schema'),['SQL列','原列名','类型','缺失','不同值'],source.columns.map(c=>[c.key,c.name,c.type,c.missing,c.distinct]));table($('#preview'),source.columns.map(c=>c.name),source.preview);$('#execute-form').reset();$('#question-form').reset();initBuilder(source);$('#proposal-note').textContent='可以手工编写，只允许查询表 data。';$('#propose').disabled=!configured;await Promise.all([histories(id),list()]);}
function display(run){shown=run;const r=run.result;$('#result-panel').hidden=false;$('#executed-sql').textContent=run.sql;$('#result-note').textContent=r.state==='failed'?r.error:`显示 ${r.rows.length} 行${r.truncated?'（结果已截断至200行）':''}。${r.notice}`;$('#chart-panel').hidden=r.state!=='succeeded';$('#result-table').replaceChildren();if(r.state==='succeeded'){table($('#result-table'),r.columns,r.rows);for(const id of ['#label-column','#value-column']){$(id).replaceChildren(...r.columns.map((name,i)=>{const o=el('option',name);o.value=String(i);return o;}));}const numeric=r.columns.findIndex((_,i)=>r.rows.length&&r.rows.every(row=>typeof row[i]==='number'&&Number.isFinite(row[i])));$('#value-column').value=String(numeric<0?0:numeric);drawChart();}$('#result-panel').scrollIntoView({behavior:'smooth',block:'start'});}
function drawChart(){const r=shown?.result;if(!r||r.state!=='succeeded')return;const label=Number($('#label-column').value),value=Number($('#value-column').value),rows=r.rows.slice(0,20);$('#chart').replaceChildren();if(!rows.length||rows.some(row=>typeof row[value]!=='number'||!Number.isFinite(row[value]))){$('#chart').append(el('p','所选列包含非数值或NULL，未绘图。请查看表格或在SQL中明确处理。'));return;}const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 700 ${rows.length*36+40}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',`${r.columns[label]}与${r.columns[value]}条形图，详细数值见表格`);const min=Math.min(0,...rows.map(row=>row[value])),max=Math.max(0,...rows.map(row=>row[value])),span=max-min||1,scale=v=>170+(v-min)/span*430;const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;svg.append(n);return n;};add('line',{x1:scale(0),x2:scale(0),y1:10,y2:rows.length*36+10,stroke:'#8391b2'});rows.forEach((row,i)=>{const y=i*36+14,v=row[value];add('text',{x:5,y:y+16,'font-size':12,fill:'#3b465a'},String(row[label]??'NULL').slice(0,18));add('rect',{x:Math.min(scale(0),scale(v)),y,width:Math.abs(scale(v)-scale(0)),height:23,fill:v<0?'#b8725f':'#536dc1'});add('text',{x:615,y:y+16,'font-size':12,fill:'#3b465a'},String(v));});$('#chart').append(svg);}
$('#label-column').onchange=drawChart;$('#value-column').onchange=drawChart;$('#sql').oninput=()=>$('#reviewed').checked=false;
$('#manual').onclick=()=>{proposalId=null;$('#reviewed').checked=false;$('#proposal-note').textContent='独立手工查询，不关联模型提议。';};
$('#question-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;const id=selected.id;try{notice('免费模型生成SQL提议中…');const p=await api(`/datasets/${id}/proposals`,{question:$('#question').value});if(selected?.id===id){useProposal(p);await histories(id);}notice('SQL提议已保存，尚未执行。请核对后确认。');}catch(e){notice(e.message,true);await histories(id);}finally{b.disabled=false;}};
$('#execute-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;const id=selected.id;try{const sql=$('#sql').value,result=await api(`/datasets/${id}/runs`,{sql,proposal_id:proposalId,note:$('#review-note').value,reviewed:$('#reviewed').checked});if(selected?.id===id){display({id:result.id,sql,result});await histories(id);}notice(result.state==='succeeded'?'查询完成，结果和审核说明已留存。':'查询未成功，失败记录已保留。',result.state!=='succeeded');}catch(e){notice(e.message,true);}finally{b.disabled=false;}};
action($('#download'),async()=>{if(!shown)return;const record=await api('/runs/'+shown.id),url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download=`databrief-${shown.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{if(f.size>2000000)throw Error('CSV超过2MB');const r=await api('/datasets?name='+encodeURIComponent(f.name),await f.arrayBuffer(),true);await load(r.id);notice(r.duplicate?'已打开相同数据的原记录。':'数据已导入。请先核对类型和缺失值。');}catch(e){notice(e.message,true);}finally{e.target.value='';}};
action($('#sample'),async()=>{const response=await fetch('/sample.csv');if(!response.ok)throw Error('样例无法读取');const r=await api('/datasets?name='+encodeURIComponent('合成渠道数据'),await response.arrayBuffer(),true);await load(r.id);notice('已打开合成数据：金额总和60，订单数非空平均值2.5。');});
$('#token').onclick=()=>{const token=prompt('工作台访问令牌（仅当前标签页保存）');if(token!==null){sessionStorage.setItem('dbr-token',token);location.reload();}};
(async()=>{try{const s=await api('/status');configured=s.model_configured;$('#model-status').textContent=configured?'免费模型已配置 · 查询需核对':'模型未配置 · 可手工查询';await list();}catch(e){notice(e.message,true);}})();

function initBuilder(source){
 $('#builder-form').reset();$('#builder-note').textContent='';
 for(const [id,label] of [['#builder-group','不分组'],['#builder-filter','不筛选'],['#builder-metric','请选择指标列']]){
  const empty=el('option',label);empty.value='';
  $(id).replaceChildren(empty,...source.columns.map(c=>{const o=el('option',`${c.name} (${c.key} / ${c.type})`);o.value=c.key;return o;}));
 }
 updateBuilder();
}
function updateBuilder(){
 const aggregate=$('#builder-aggregate').value,isRows=aggregate==='rows',isCount=['rows','count','distinct'].includes(aggregate);
 $('#builder-metric').disabled=isRows;if(isRows)$('#builder-metric').value='';
 $('#builder-nulls').disabled=isCount;if(isCount)$('#builder-nulls').value='exclude';
 const filter=$('#builder-filter').value,empty=['missing','present'].includes($('#builder-operator').value);
 $('#builder-operator').disabled=!filter;$('#builder-value').disabled=!filter||empty;
 if(!filter||empty)$('#builder-value').value='';
 $('#builder-note').textContent='选项已更改；点击生成后才会替换 SQL 编辑区。';
}
for(const id of ['#builder-aggregate','#builder-metric','#builder-group','#builder-nulls','#builder-filter','#builder-operator','#builder-order'])$(id).onchange=updateBuilder;
$('#builder-value').oninput=()=>$('#builder-note').textContent='比较值已更改；请重新生成查询。';
$('#builder-form').onsubmit=async e=>{
 e.preventDefault();const b=e.submitter,id=selected.id;b.disabled=true;
 try{
  const filter=$('#builder-filter').value;
  const p=await api(`/datasets/${id}/query-preview`,{aggregate:$('#builder-aggregate').value,metric:$('#builder-metric').value,group:$('#builder-group').value,nulls:$('#builder-nulls').value,order:$('#builder-order').value,filter:filter?{column:filter,operator:$('#builder-operator').value,value:$('#builder-value').value}:null});
  if(selected?.id!==id)return;
  proposalId=null;$('#sql').value=p.sql;$('#reviewed').checked=false;$('#review-note').value='';
  $('#proposal-note').textContent='可视化查询（非模型生成）：'+p.explanation;
  $('#builder-note').textContent=p.notice;notice('已生成查询并载入编辑区，尚未执行。');
 }catch(e){notice(e.message,true);}finally{b.disabled=false;}
};
