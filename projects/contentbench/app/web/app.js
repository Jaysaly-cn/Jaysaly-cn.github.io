'use strict';
const $ = s => document.querySelector(s);
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
let current = null, editing = null, channels = {}, configured = false;
function notice(text, error = false) { $('#message').textContent = text; $('#message').className = error ? 'error' : ''; }
async function api(path, data) {
  const headers = {Authorization: 'Bearer ' + (sessionStorage.getItem('cb-token') || '')};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const r = await fetch('/api' + path, {method: data === undefined ? 'GET' : 'POST', headers, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await r.json();
  if (!r.ok) throw Error(typeof result.detail === 'string' ? result.detail : '输入格式不正确，请检查必填字段与长度');
  return result;
}
function action(button, fn) { button.addEventListener('click', async () => {button.disabled = true; try { await fn(); } catch (e) { notice(e.message, true); } finally {button.disabled = false;}}); }
function factIds() {return [...document.querySelectorAll('#fact-choices input:checked')].map(i => i.value);}
function resetEditor() {editing = null; $('#copy-form').reset(); $('#channel').disabled = false; $('#editor-title').textContent = '创建稿件'; $('#cancel-edit').hidden = true; $('#save-copy').textContent = '保存待审核稿件'; updateLimit();}
function updateLimit() {$('#channel-limit').textContent = `正文上限 ${channels[$('#channel').value] || '—'} 字符（本工作台约定）`;}
async function list() {
  const list = await api('/campaigns'); $('#campaigns').replaceChildren();
  list.forEach(c => {const b = el('button', c.brief.name, c.id === current?.id ? 'active' : ''); action(b, () => load(c.id)); $('#campaigns').append(b);});
}
async function load(id) {
  current = await api('/campaigns/' + id); resetEditor(); $('#welcome').hidden = true; $('#create').hidden = true; $('#workspace').hidden = false;
  $('#campaign-title').textContent = current.brief.name; $('#campaign-meta').textContent = `${current.brief.audience} · ${current.brief.objective} · ${current.brief.tone}`;
  $('#facts').replaceChildren(); $('#fact-choices').replaceChildren();
  current.brief.facts.forEach(f => {
    const p = el('div', `${f.id} · ${f.text}\n出处：${f.source}`, 'fact'); $('#facts').append(p);
    const label = el('label', undefined, 'check'), box = el('input'); box.type = 'checkbox'; box.value = f.id; label.append(box, el('span', `${f.id} · ${f.text}`)); $('#fact-choices').append(label);
  });
  $('#facts').append(el('p', '禁用词：' + (current.brief.forbidden.join('、') || '未设置')), el('p', '必带说明：' + (current.brief.required_phrase || '未设置')));
  $('#draft-count').textContent = current.drafts.length + ' 份稿件'; $('#drafts').replaceChildren();
  current.drafts.forEach(renderDraft);
  $('#exports').replaceChildren();
  if (!current.exports.length) $('#exports').append(el('p', '尚无导出记录。审核通过后可冻结稿件。', 'muted'));
  current.exports.forEach(x => {
    const row=el('div',undefined,'actions'); row.append(el('span',new Date(x.created_at).toLocaleString()));
    for(const [format,label,extension] of [['json','下载 JSON','json'],['markdown','下载 Markdown','md']]) {
      const b=el('button',label,'secondary');
      action(b,async()=>{
        const response=await fetch('/api/exports/'+x.id+'?format='+format,{headers:{Authorization:'Bearer '+(sessionStorage.getItem('cb-token')||'')}});
        if(!response.ok){const error=await response.json();throw Error(error.detail||'下载失败');}
        const url=URL.createObjectURL(await response.blob()),a=el('a');a.href=url;a.download='contentbench-'+x.id+'.'+extension;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        notice('已请求下载冻结快照；后续修改不影响此版本。');
      });row.append(b);
    }$('#exports').append(row);
  });
  $('#events').replaceChildren(...current.events.map(e => el('div', `${new Date(e.created_at).toLocaleString()} · ${e.action} · ${e.detail}`, 'event')));
  await list();
}
function comparison(d) {
  const box=el('details',undefined,'comparison'); box.append(el('summary','对比修订内容'));
  const controls=el('div',undefined,'grid'), selects=[];
  for (const [i,title] of ['修改前','修改后'].entries()) {
    const label=el('label',title), select=el('select');
    [...d.revisions].reverse().forEach(r=>{const option=el('option',`v${r.number} · ${r.title}`);option.value=r.id;select.append(option);});
    select.value=d.revisions[i===0?1:0].id; label.append(select);controls.append(label);selects.push(select);
  }
  const button=el('button','显示差异','secondary'), result=el('div');result.setAttribute('aria-live','polite');
  action(button,async()=>{
    const data=await api(`/drafts/${d.id}/compare?before=${encodeURIComponent(selects[0].value)}&after=${encodeURIComponent(selects[1].value)}`);
    result.replaceChildren(el('h3',`v${data.before.number} → v${data.after.number}`),el('p',data.notice,'muted'));
    for(const [field,title] of [['title','标题'],['body','正文']]) {
      result.append(el('h3',title));
      for(const part of data.changes[field]) {
        if(part.operation==='equal') result.append(el('pre','未变 · '+part.after,'diff-equal'));
        else {if(part.before)result.append(el('pre','删除 − '+part.before,'diff-removed'));if(part.after)result.append(el('pre','新增 + '+part.after,'diff-added'));}
      }
    }
    result.append(el('p',`关联事实新增：${data.facts_added.join('、')||'无'}；移除：${data.facts_removed.join('、')||'无'}`));
    for(const [title,revision] of [['修改前',data.before],['修改后',data.after]]) {
      result.append(el('h3',`${title}规则与审核`),el('p',revision.checks.blockers.map(i=>i.detail).join('；')||'规则检查通过'),el('p',`状态：${{draft:'待审核',approved:'已批准',rejected:'已退回'}[revision.state]}；审核说明：${revision.review_note||'尚未审核'}`));
    }
  });
  selects.forEach(s=>s.addEventListener('change',()=>result.replaceChildren()));
  box.append(controls,button,result);return box;
}
function renderDraft(d) {
  const r = d.revisions[0], card = el('article', undefined, 'draft'), head = el('div', undefined, 'section-head');
  head.append(el('h2', r.title), el('span', `${d.channel} · v${r.number} · ${{draft:'待审核',approved:'已批准',rejected:'已退回'}[r.state]}`, 'tag')); card.append(head, el('p', `${r.origin === 'model' ? '模型起草 · ' + r.model : '人工录入/修订'} · 关联 ${r.fact_ids.join('、') || '无事实'}`, 'muted'), el('div', r.body, 'body'));
  const issues = r.checks.blockers; card.append(el('p', issues.length ? issues.map(i => i.detail).join('；') : '规则检查通过；仍需逐句核对事实含义与条件。', issues.length ? 'issues' : 'good'));
  const edit = el('button', '创建修订版', 'secondary'); action(edit, () => {
    editing = {draft:d.id, revision:r.id}; $('#editor-title').textContent = `修订 v${r.number} → v${r.number+1}`; $('#channel').value = d.channel; $('#channel').disabled = true;
    $('#copy-form').elements.title.value = r.title; $('#copy-form').elements.body.value = r.body;
    document.querySelectorAll('#fact-choices input').forEach(i => i.checked = r.fact_ids.includes(i.value)); $('#cancel-edit').hidden = false; $('#save-copy').textContent = '保存新版本（重新审核）'; updateLimit(); $('#editor-title').scrollIntoView({behavior:'smooth'});
  }); card.append(edit);
  if (r.state === 'draft') {
    const review = el('div', undefined, 'review'), label = el('label', '审核说明（至少 5 字）'), note = el('textarea'); note.rows = 2; label.append(note);
    const confirm = el('label', undefined, 'check'), checked = el('input'); checked.type='checkbox'; confirm.append(checked, el('span', '我已逐句核对关联事实、来源、条件与措辞'));
    const buttons = el('div', undefined, 'actions');
    for (const [state,text] of [['approved','批准当前版本'],['rejected','退回修改']]) {const b = el('button',text,state === 'rejected' ? 'danger' : ''); action(b, async () => {await api('/revisions/' + r.id + '/review',{state,version:r.version,note:note.value,facts_checked:checked.checked}); await load(current.id); notice(text + '已保存');}); buttons.append(b);}
    review.append(label,confirm,buttons); card.append(review);
  } else card.append(el('p','审核说明：' + r.review_note,'muted'));
  if (d.revisions.length > 1) {const history = el('details'); history.append(el('summary','查看历史版本 · ' + (d.revisions.length-1))); d.revisions.slice(1).forEach(old => {history.append(el('h3',`v${old.number} · ${old.title} · ${old.state}`),el('pre',old.body),el('p','审核说明：' + (old.review_note || '未审核')));}); card.append(history);}
  if(d.revisions.length>1)card.append(comparison(d));
  $('#drafts').append(card);
}
$('#new').onclick = () => {$('#create').hidden = false; $('#welcome').hidden = true; $('#workspace').hidden = true;};
$('#sample').onclick = () => {$('#new').click(); const f=$('#brief-form').elements; f.name.value='拾光任务本 · 合成产品示例';f.audience.value='希望整理每周任务的职场新人'; f.objective.value='邀请体验任务整理功能';f.tone.value='清晰、克制、友好';f.facts.value='支持手动添加任务和设置截止日期 | 合成产品说明 v1\n支持按周查看任务清单 | 合成产品说明 v1';f.forbidden.value='行业第一\n保证\n最强';f.required_phrase.value='示例产品，仅供学习';};
$('#auth').onclick = () => {const token=prompt('输入工作台访问令牌（仅保存在当前标签页）'); if(token!==null){sessionStorage.setItem('cb-token',token);location.reload();}};
$('#channel').onchange=updateLimit; $('#cancel-edit').onclick=resetEditor;
$('#brief-form').onsubmit=async e=>{e.preventDefault(); const b=e.submitter;b.disabled=true;try{const f=e.target.elements; const facts=f.facts.value.split('\n').filter(x=>x.trim()).map((line,i)=>{const cut=line.indexOf('|');if(cut<0)throw Error('每条事实请用 | 分隔内容与出处');return{id:'F'+(i+1),text:line.slice(0,cut).trim(),source:line.slice(cut+1).trim()};});const c=await api('/campaigns',{name:f.name.value,audience:f.audience.value,objective:f.objective.value,tone:f.tone.value,facts,forbidden:f.forbidden.value.split('\n').map(x=>x.trim()).filter(Boolean),required_phrase:f.required_phrase.value});await load(c.id);notice('活动已保存，开始准备稿件');}catch(error){notice(error.message,true);}finally{b.disabled=false;}};
$('#copy-form').onsubmit=async e=>{e.preventDefault(); const b=e.submitter;b.disabled=true;try{const f=e.target.elements;const copy={title:f.title.value,body:f.body.value,fact_ids:factIds()};if(editing)await api('/drafts/'+editing.draft+'/revisions',{...copy,expected_revision:editing.revision});else await api('/campaigns/'+current.id+'/drafts',{...copy,channel:f.channel.value});await load(current.id);notice('已保存为待审核版本');}catch(error){notice(error.message,true);}finally{b.disabled=false;}};
action($('#generate'),async()=>{if(editing)throw Error('请先保存或取消当前修订，再生成独立稿件');if(!configured)throw Error('免费模型尚未配置，可以先手工录入稿件');const id=current.id;notice('模型正在起草，通常需要数秒至一分钟…');await api('/campaigns/'+id+'/generate',{channel:$('#channel').value});await load(id);notice('模型稿件已保存，请检查规则提示并逐句审核');});
action($('#export'),async()=>{const x=await api('/campaigns/'+current.id+'/exports',{});await load(current.id);notice(`已冻结 ${x.copies.length} 份最新批准稿件；可在导出记录中下载。`);});
(async()=>{try{const s=await api('/status');channels=s.channels;configured=s.model_configured;$('#model-status').textContent=configured?'免费模型已配置 · 生成结果仍需审核':'免费模型未配置 · 可使用手工稿件流程';updateLimit();await list();}catch(e){notice(e.message,true);}})();
