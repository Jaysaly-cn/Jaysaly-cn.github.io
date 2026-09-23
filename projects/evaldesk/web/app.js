'use strict';
const $=id=>document.getElementById(id);
const statusNames={passed:'断言通过',assertion_failed:'断言失败',call_error:'调用错误'};
const decisionNames={pending:'待复核',accepted:'符合业务要求',rejected:'不符合业务要求',unclear:'无法判断'};
let current=null,dirty=false,busy=false,filterValue='all';
function el(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function notice(text){$('notice').textContent=text;}
async function api(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;}
function post(url,data){return api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}
function lock(value){busy=value;document.querySelectorAll('input,textarea,select,button').forEach(n=>n.disabled=value);}
function mayLeave(){if(!dirty)return true;notice('存在未保存草稿。请先保存，或点击“丢弃本页未保存草稿”后再切换。');$('discard').hidden=false;return false;}
function field(form,title,name,node){node.name=name;const label=el('label',title);label.append(node);form.append(label);return node;}
function render(){
  $('summary').replaceChildren();$('cases').replaceChildren();$('prompts').replaceChildren();
  if(!current)return;
  for(const metric of current.summary){const card=el('article',undefined,'metric');card.append(el('h3',metric.prompt_id));card.append(el('strong',`${metric.passed} / ${metric.total}`));card.append(el('p',`自动断言通过 · 失败 ${metric.assertion_failed} · 调用错误 ${metric.call_error}`));card.append(el('p',`人工已复核 ${metric.total-metric.pending}/${metric.total} · 待复核 ${metric.pending}`,'human'));card.append(el('p',`符合 ${metric.accepted} · 不符合 ${metric.rejected} · 无法判断 ${metric.unclear}`));$('summary').append(card);}
  const m=current.manifest;
  $('provenance').textContent=`运行 ${m.id} · ${m.status} · ${m.started_at} · 测试集 SHA-256 ${m.suite_sha256}`;
  for(const p of current.suite.prompts){$('prompts').append(el('h4',p.id),el('pre',p.instruction));}
  $('prompts').append(el('pre',JSON.stringify(current.config.providers,null,2)));
  let visible=0;
  current.suite.cases.forEach((c,ci)=>{
    const cells=current.cells.filter(v=>v.case_index===ci);
    const filter=$('filter').value;
    if(filter==='failed'&&!cells.some(v=>v.status==='assertion_failed'))return;
    if(filter==='pending'&&!cells.some(v=>v.review.decision==='pending'))return;
    if(filter==='error'&&!cells.some(v=>v.status==='call_error'))return;
    visible++;
    const article=el('article',undefined,'case'),head=el('div',undefined,'case-head');
    head.append(el('h4',`${String(ci+1).padStart(2,'0')} / ${c.id}`),el('div',c.input,'input'),el('p','业务判据：'+c.rubric));
    const assertions=el('details');assertions.append(el('summary','查看自动检查规则'),el('pre',JSON.stringify(c.checks,null,2)));head.append(assertions);article.append(head);
    const comparison=el('div',undefined,'comparison');
    for(const cell of cells){
      const answer=el('section',undefined,'answer'),top=el('div',undefined,'answer-top');top.append(el('h5',cell.prompt_id),el('span',statusNames[cell.status],'badge '+cell.status));
      answer.append(top,el('pre',cell.output===null?'未产生可用输出':cell.output,'output'),el('p',cell.reason,'reason'));
      const form=el('form',undefined,'review-form');form.dataset.cell=cell.id;
      form.append(el('p',`人工判断：${decisionNames[cell.review.decision]} · 修订 ${cell.review.version}`,'review-state'));
      const select=field(form,'业务判断','decision',el('select'));select.required=true;const empty=el('option','请选择');empty.value='';select.append(empty);
      for(const key of ['accepted','rejected','unclear']){const o=el('option',decisionNames[key]);o.value=key;o.disabled=key==='accepted'&&cell.status==='call_error';select.append(o);}select.value=cell.review.decision==='pending'?'':cell.review.decision;
      const reviewer=field(form,'复核者（自报）','reviewer',el('input'));reviewer.required=true;reviewer.maxLength=80;reviewer.value=cell.review.reviewer;
      const note=field(form,'判断理由','note',el('textarea'));note.required=true;note.minLength=5;note.maxLength=2000;note.value=cell.review.note;
      const button=el('button',cell.review.version?'保存修订':'保存人工判断');button.type='submit';form.append(button);
      form.addEventListener('input',()=>dirty=true);
      form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;const payload={version:cell.review.version,decision:select.value,reviewer:reviewer.value,note:note.value};lock(true);
        try{const updated=await post(`/api/runs/${current.manifest.id}/cells/${cell.id}/reviews`,payload);
          // Keep other cards' unsaved text: update only this cell after success.
          const saved=updated.cells.find(v=>v.id===cell.id);cell.review=saved.review;cell.history=saved.history;current=updated;
          form.querySelector('.review-state').textContent=`人工判断：${decisionNames[saved.review.decision]} · 修订 ${saved.review.version}`;
          form.dataset.saved='true';button.textContent='保存修订';renderMetrics();renderHistory(history,saved);
          dirty=Array.from(document.querySelectorAll('.review-form')).some(f=>f!==form&&f.dataset.dirty==='true')||$('report-form').dataset.dirty==='true';form.dataset.dirty='false';$('discard').hidden=!dirty;notice('人工判断已保存；自动断言结果保持原样。');
        }catch(e){notice(e.message);}finally{lock(false);}
      });
      form.addEventListener('input',()=>form.dataset.dirty='true');
      const history=el('details',undefined,'history');renderHistory(history,cell);answer.append(form,history);comparison.append(answer);
    }
    if(!cells.length)comparison.append(el('p','引擎未完成有效结果，不能计算通过率。','empty'));
    article.append(comparison);$('cases').append(article);
  });
  $('case-count').textContent=`显示 ${visible} / ${current.suite.cases.length} 个样例`;
  if(!visible)$('cases').append(el('p','没有符合筛选条件的样例。','empty'));
}
function renderMetrics(){/* Preserve every form while updating numbers only. */
  for(let i=0;i<current.summary.length;i++){const m=current.summary[i],card=$('summary').children[i];card.querySelector('.human').textContent=`人工已复核 ${m.total-m.pending}/${m.total} · 待复核 ${m.pending}`;card.lastChild.textContent=`符合 ${m.accepted} · 不符合 ${m.rejected} · 无法判断 ${m.unclear}`;}}
function renderHistory(target,cell){target.replaceChildren(el('summary',`判断历史（${cell.history.length}）`));for(const h of [...cell.history].reverse())target.append(el('p',`v${h.version} · ${decisionNames[h.decision]} · ${h.reviewer}\n${h.note}\n${h.created_at}`));}
async function loadReports(){const reports=await api(`/api/runs/${current.manifest.id}/reports`);$('reports').replaceChildren();for(const r of reports){const a=el('a',`下载：${r.title} · ${r.created_at}`);a.href=`/api/reports/${r.id}`;a.download='evaldesk-report.json';$('reports').append(a);}}
async function load(id){lock(true);try{current=await api('/api/runs/'+id);dirty=false;$('report-form').reset();$('report-form').dataset.dirty='false';render();await loadReports();notice('');}catch(e){notice(e.message);}finally{lock(false);}}
async function refresh(){if(busy||!mayLeave())return;lock(true);try{const rows=await api('/api/runs');const previous=current?.manifest.id||new URLSearchParams(location.search).get('run');$('run-select').replaceChildren();for(const r of rows){const o=el('option',`${r.name} · ${r.id.slice(0,8)}`);o.value=r.id;$('run-select').append(o);}if(!rows.length){notice('尚无运行记录。请通过 store.py 导入已完成的评测证据。');return;}const selected=rows.some(r=>r.id===previous)?previous:rows[0].id;$('run-select').value=selected;await load(selected);}catch(e){notice(e.message);}finally{lock(false);}}
$('run-select').addEventListener('change',()=>{if(!mayLeave()){$('run-select').value=current.manifest.id;return;}load($('run-select').value);});
$('refresh').addEventListener('click',refresh);
$('discard').addEventListener('click',()=>{if(busy)return;dirty=false;$('discard').hidden=true;$('report-form').reset();$('report-form').dataset.dirty='false';render();notice('未保存草稿已丢弃，已保存的判断保留。');});
$('filter').addEventListener('change',()=>{if(!mayLeave()){$('filter').value=filterValue;return;}filterValue=$('filter').value;dirty=false;$('report-form').reset();$('report-form').dataset.dirty='false';render();});
$('report-form').addEventListener('input',()=>{dirty=true;$('report-form').dataset.dirty='true';});
$('report-form').addEventListener('submit',async event=>{event.preventDefault();if(!current||busy)return;if([...document.querySelectorAll('.review-form')].some(f=>f.dataset.dirty==='true')){notice('请先保存或丢弃未保存的人工判断，再冻结报告。');return;}const f=new FormData(event.target);lock(true);try{await post(`/api/runs/${current.manifest.id}/reports`,{title:f.get('title'),note:f.get('note')});event.target.reset();event.target.dataset.dirty='false';dirty=false;await loadReports();notice('报告已冻结。后续人工判断的修订不会改变该报告。');}catch(e){notice(e.message);}finally{lock(false);}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
refresh();
