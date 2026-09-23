'use strict';
let chosenBatch=null,batchBusy=false;
const batchStates={pending:'待执行',running:'正在执行',interrupted:'中断，可继续',success:'已处理，候选待审核',failed:'失败，可显式重试'};
function batchSources(changed){
 if(document.body.classList.contains('demo-mode'))return;
 if(changed){chosenBatch=null;$('batch-detail').hidden=true;$('batch-progress').textContent='';}
 const previously=new Set([...$('batch-sources').querySelectorAll('input:checked')].map(c=>c.value));
 $('batch-sources').replaceChildren(...data.sources.filter(s=>!s.archived).map(s=>{
  const label=el('label'),input=el('input');input.type='checkbox';input.value=s.id;input.checked=!changed&&previously.has(s.id);
  label.append(input,el('span',`${s.entity} · ${s.title} · ${s.content.length}字符`));return label;
 }));
 if(!$('batch-sources').children.length)$('batch-sources').append(el('p','先在来源资料中保存材料。','muted'));
}
async function loadBatches(projectId=pid){
 if(document.body.classList.contains('demo-mode'))return;
 const rows=await api(`/projects/${projectId}/batches`);if(pid!==projectId)return;
 $('batch-list').replaceChildren(...rows.map(r=>button(`${new Date(r.created_at).toLocaleString()} · ${r.steps.filter(s=>s.state==='success').length}/${r.steps.length}步 · ${r.paused?'已暂停':r.complete?'处理完成':'待继续'}`,()=>{chosenBatch=r;renderBatch();})));
 if(!rows.length)$('batch-list').append(el('p','还没有执行计划。','muted'));
 if(chosenBatch){const current=rows.find(r=>r.id===chosenBatch.id);if(current&&current.updated_at>=chosenBatch.updated_at)chosenBatch=current;renderBatch();}
}
function renderBatch(){
 if(!chosenBatch)return;
 const r=chosenBatch,waiting=r.steps.some(s=>['pending','interrupted'].includes(s.state)),failed=r.steps.some(s=>s.state==='failed'),running=r.steps.some(s=>s.state==='running');
 $('batch-detail').hidden=false;$('batch-title').textContent='计划 '+r.id.slice(0,8);
 $('batch-summary').textContent=`${r.steps.filter(s=>s.state==='success').length}/${r.steps.length}步已处理 · ${r.paused?'已暂停':r.complete?'全部步骤已处理，仍需审核':'尚未完成'} · ${failed?'有失败步骤':''}`;
 const blocked=batchBusy||segmentBusy||!modelReady||r.paused||running;
 $('batch-next').disabled=blocked||!waiting;$('batch-three').disabled=blocked||!waiting;
 $('batch-retry').disabled=blocked||waiting||!failed;
 $('batch-pause').textContent=r.paused?'恢复计划（不自动执行）':'暂停计划';
 $('batch-steps').replaceChildren(...r.steps.map((s,i)=>{const card=el('article');card.append(el('strong',`${i+1}. ${s.title} · 第${s.index+1}段`),el('p',`${batchStates[s.state]} · 尝试${s.attempts}次 · ${s.claim_ids.length}个候选引用${s.cached?' · 复用已保存分段':''}`),el('small',`原文范围 [${s.start}, ${s.end}) · SHA-256 ${s.sha256}`));if(s.error)card.append(el('p',s.error));return card;}));
}
$('batch-create').onsubmit=e=>{e.preventDefault();safe(async()=>{
 const projectId=pid,ids=[...$('batch-sources').querySelectorAll('input:checked')].map(c=>c.value);
 if(!ids.length||ids.length>8)throw Error('请选择1至8份未归档资料。');
 const button=$('batch-create-button');button.disabled=true;
 try{const created=await post(`/projects/${projectId}/batches`,{source_ids:ids});if(pid!==projectId)return;chosenBatch=created;await loadBatches(projectId);notice('计划已保存，尚未执行；请选择下一步或最多3步。');}finally{button.disabled=false;}
});};
async function runBatch(limit,retry=false){
 if(batchBusy||!chosenBatch)return;
 const projectId=pid,bid=chosenBatch.id;batchBusy=true;renderBatch();
 try{
  for(let i=0;i<limit;i++){
   if(pid!==projectId||chosenBatch?.id!==bid)break;
   $('batch-progress').textContent=`已请求第${i+1}/${limit}步；可刷新查看后端状态，暂停不会强制终止当前请求。`;
   const previous=chosenBatch.steps.map(s=>s.attempts);
   const result=await post(`/projects/${projectId}/batches/${bid}/next`,{retry_failed:retry});
   if(pid!==projectId||chosenBatch?.id!==bid)break;
   chosenBatch=result;renderBatch();
   const newFailure=result.steps.some((s,j)=>s.state==='failed'&&s.attempts>previous[j]);
   if(newFailure||result.paused||result.complete||!result.steps.some((s,j)=>s.attempts>previous[j]))break;
  }
  if(pid===projectId&&chosenBatch?.id===bid){await loadBatches(projectId);$('batch-progress').textContent='本次执行请求结束。成功步骤保留；失败步骤需显式重试。请进入结论审核核对候选与遗漏。';}
 }catch(error){if(pid===projectId&&chosenBatch?.id===bid)$('batch-progress').textContent='请求未完成。请刷新核对后端步骤状态，再决定是否继续。';throw error;
 }finally{batchBusy=false;if(chosenBatch)renderBatch();}
}
$('batch-next').onclick=()=>safe(()=>runBatch(1));$('batch-three').onclick=()=>safe(()=>runBatch(3));$('batch-retry').onclick=()=>safe(()=>runBatch(1,true));
$('batch-refresh').onclick=()=>safe(()=>loadBatches());
$('batch-pause').onclick=()=>safe(async()=>{if(!chosenBatch)return;const projectId=pid,bid=chosenBatch.id;const result=await post(`/projects/${projectId}/batches/${bid}/pause`,{paused:!chosenBatch.paused});if(pid===projectId&&chosenBatch?.id===bid){chosenBatch=result;renderBatch();}});
$('batch-claims').onclick=()=>safe(async()=>{const projectId=pid;await openProject(projectId);if(pid===projectId)tab('claims');});
