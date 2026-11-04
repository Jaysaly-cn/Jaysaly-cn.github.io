import {initial,transition,ready} from './agent-workspace-core.mjs';

const $=id=>document.getElementById(id);
const element=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
let state=initial(),selectedFile=null,feedbackTimer;
const edits=new Map(),reviewDrafts=new Map(),reviewers=new Map();
const currentFiles=()=>state.files.filter(f=>f.revision===state.revision);
const reviewed=f=>f.reviews.some(r=>r.version===f.version&&r.reviewer!==f.author);
const keyFor=f=>`${f.id}:${f.version}`;
const hasUnsaved=()=>[...edits].some(([id,text])=>text!==state.files.find(f=>f.id===id)?.text);

function feedback(message,error=false){
  clearTimeout(feedbackTimer);
  $('message').textContent=message;
  $('feedback-icon').textContent=error?'!':'✓';
  $('feedback').classList.toggle('error',error);
  $('feedback').hidden=false;
  if(!error)feedbackTimer=setTimeout(()=>$('feedback').hidden=true,6500);
}
function status(id,text,tone=''){$(id).textContent=text;$(id).className=`status-tag ${tone}`;}
function actionButton(action,disabled,label){const b=document.querySelector(`[data-action="${action}"]`);b.disabled=disabled;if(label)b.textContent=label;}

function dispatch(action,data={}){
  try{
    if(['goal','return','retire'].includes(action)&&hasUnsaved())throw Error('还有未保存的原件。请先保存修订，再改变工作安排。');
    if(action==='accept'&&hasUnsaved())throw Error('还有未保存的原件。请先保存并重新复核，再接受交付。');
    state=transition(state,action,data);
    if(action==='edit')edits.delete(data.id);
    if(action==='draft')selectedFile=state.files.at(-1).id;
    if(['goal','return'].includes(action)){$('goal-panel').open=action==='return';$('acceptance').value='';}
    render();feedback(state.events.at(-1).message);
    return true;
  }catch(e){feedback(e.message,true);return false;}
}

function renderHelix(){
  const i=state.instance,live=!!i&&!i.retired;
  $('release-state').textContent=state.release?'1.0.0 已发布 · 固定版本':'发布后，这个版本即可用于部署。';
  $('instance-state').textContent=i?`${i.executor} 实例${i.retired?'已退役，历史记录保留。':'已部署，运行准备单独记录。'}`:'发布后即可部署。';
  $('device-state').textContent=live?`执行配置${i.credentials?'已就绪':'待准备'}；设备 ACK${i.ack?'已确认':'待确认'}。`:'部署实例后，逐项完成检查。';
  $('fact-release').textContent=state.release?'1.0.0':'尚未发布';
  $('fact-executor').textContent=i?.executor||'尚未配置';
  $('fact-device').textContent=live?(i.ack?'已确认':'等待 ACK'):i?.retired?'实例已退役':'等待部署';
  $('diagram-executor').textContent=i?.executor||'待选择';
  const checks=live?[i.credentials,i.ack,i.evaluated]:[false,false,false];
  $('readiness-count').textContent=`${checks.filter(Boolean).length} / 3 项已完成`;
  for(const [id,done] of [['credentials-check',checks[0]],['ack-check',checks[1]],['evaluation-check',checks[2]]]){$(id).classList.toggle('done',done);$(id).textContent=done?'✓':'';}
  const stages=[state.release,live,live&&i.credentials&&i.ack&&i.evaluated,!!i?.active];
  const next=stages.findIndex(done=>!done);
  for(const [index,id] of ['diagram-release','diagram-instance','diagram-device','diagram-active'].entries()){
    $(id).classList.toggle('done',!!stages[index]);$(id).classList.toggle('current',index===next);
  }
  for(const [index,a] of [...document.querySelectorAll('.lifecycle a')].entries()){
    a.classList.toggle('done',!!stages[index]);a.classList.toggle('current',index===next);
    if(index===next)a.setAttribute('aria-current','step');else a.removeAttribute('aria-current');
  }
  status('overview-status',i?.retired?'已退役':i?.active?'已激活':live?'运行准备中':'等待准备',i?.active?'ready':live?'progress':'');
  let title='发布员工版本',description='版本发布后，选择执行器开始部署。';
  if(state.release){title='部署运行实例';description='选择 Codex、Claude Code 或 DeepSeek。';}
  if(live){title='完成运行前检查';description='先备齐配置和设备 ACK，再运行规则测评。';}
  if(live&&i.evaluated){title='运行条件已备齐';description='激活这个实例，即可在 CoAgents 开始协作。';}
  if(i?.active){title='实例已就绪，可以开始协作';description='前往 CoAgents，发布项目目标并检查团队交付。';}
  if(i?.retired){title='部署一个新实例';description='当前实例已退役；可以复用发布版本重新部署。';}
  $('next-step').textContent=title;$('activation-state').textContent=description;
  actionButton('publish',state.release,state.release?'版本已发布':'发布版本');
  actionButton('deploy',!state.release||live,i?.retired?'重新部署实例':'部署实例');
  $('executor').disabled=live;
  actionButton('credentials',!live||i.credentials,live&&i.credentials?'配置已就绪':'标记配置就绪');
  actionButton('ack',!live||i.ack,live&&i.ack?'设备已确认':'模拟设备 ACK');
  actionButton('evaluate',!live||!i.credentials||!i.ack||i.evaluated,live&&i.evaluated?'规则检查通过':'运行规则测评');
  actionButton('activate',!live||!i.evaluated||i.active);
  document.querySelector('[data-action="activate"]').hidden=!!i?.active;
  actionButton('retire',!live);
  $('open-coagents').hidden=!i?.active;
}

function renderDocuments(){
  const files=currentFiles(),root=$('files');root.replaceChildren();
  if(!files.some(f=>f.id===selectedFile))selectedFile=files[0]?.id??null;
  if(!files.length){
    const empty=element('div',undefined,'document-empty');
    const icon=element('span','≡','empty-document-icon');icon.setAttribute('aria-hidden','true');
    empty.append(icon,element('h3',state.revision?'等待两位作者提交原件':'先发布目标，再开始制作'),element('p',state.revision?'点击上方产品或研发按钮，生成一份可编辑的演示草稿。复核将绑定具体版本。':'把预算、使用场景和待确认问题说清楚，团队会按当前目标交稿。'));
    root.append(empty);
  }else{
    const tabs=element('div',undefined,'document-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','交付原件');
    for(const f of files){
      const tab=element('button');tab.type='button';tab.id=`file-tab-${f.id}`;tab.dataset.selectFile=f.id;tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(f.id===selectedFile));tab.setAttribute('aria-controls',`file-panel-${f.id}`);tab.tabIndex=f.id===selectedFile?0:-1;
      const dot=element('span',undefined,`tab-state ${reviewed(f)?'reviewed':''}`);dot.setAttribute('aria-hidden','true');
      tab.append(dot,element('span',f.author==='产品'?'需求说明':'研发核查清单'),element('span',`v${f.version}`));tabs.append(tab);
    }
    root.append(tabs);
    const f=files.find(f=>f.id===selectedFile),key=keyFor(f),body=element('div',undefined,'document-body');
    body.id=`file-panel-${f.id}`;body.setAttribute('role','tabpanel');body.setAttribute('aria-labelledby',`file-tab-${f.id}`);
    const heading=element('div',undefined,'document-title-row'),headingCopy=element('div');
    headingCopy.append(element('h3',f.author==='产品'?'需求说明.md':'研发核查清单.md'),element('p',`${f.author} · 目标 v${f.revision} · 原件 v${f.version}`));
    const save=element('button','保存修订','secondary');save.type='button';save.dataset.saveFile=f.id;save.disabled=!edits.has(f.id)||edits.get(f.id)===f.text;heading.append(headingCopy,save);
    const label=element('label','原件内容 · 可直接编辑','document-editor-label');label.htmlFor=`draft-${f.id}`;
    const editor=element('textarea',undefined,'draft');editor.id=`draft-${f.id}`;editor.dataset.file=f.id;editor.value=edits.get(f.id)??f.text;editor.maxLength=5000;editor.spellcheck=false;
    const hint=element('p',editor.value!==f.text?'有未保存修改，保存后需要重新复核。':'修订会保留旧稿，并重新等待非作者复核。','editor-hint');hint.id='editor-hint';hint.classList.toggle('unsaved',editor.value!==f.text);
    body.append(heading,label,editor,hint);
    const review=element('section',undefined,'review-block'),reviewHead=element('div',undefined,'review-heading');
    reviewHead.append(element('h3','独立复核'),element('span',reviewed(f)?'已记录当前版本依据':'等待非作者核对',`status-tag ${reviewed(f)?'ready':'warning'}`));review.append(reviewHead);
    for(const r of f.reviews){const row=element('div',undefined,'review-record'),copy=element('div');copy.append(element('strong',`${r.reviewer}核对 · 原件 v${r.version}`),element('p',r.evidence));row.append(element('span','✓'),copy);review.append(row);}
    const form=element('form',undefined,'review-form');form.dataset.reviewFile=f.id;
    const personLabel=element('label','非作者复核者'),select=element('select');select.id=`reviewer-${f.id}`;select.setAttribute('aria-label','非作者复核者');select.dataset.reviewer=f.id;
    for(const person of ['产品','研发','市场']){const option=element('option',person);option.disabled=person===f.author;select.append(option);}select.value=reviewers.get(key)||'市场';personLabel.append(select);
    const evidenceLabel=element('label','读取当前原件后的核对依据'),evidence=element('textarea');evidence.id=`review-evidence-${f.id}`;evidence.dataset.reviewEvidence=f.id;evidence.maxLength=800;evidence.required=true;evidence.placeholder='说明检查了什么，以及对应的结论或证据。';evidence.value=reviewDrafts.get(key)||'';evidenceLabel.append(evidence);
    const submit=element('button','记录当前版本复核');submit.type='submit';form.append(personLabel,evidenceLabel,submit);review.append(form);body.append(review);
    if(f.history.length){const history=element('details',undefined,'document-history');history.append(element('summary',`查看 ${f.history.length} 份旧版本与复核`));for(const h of f.history){history.append(element('p',`原件 v${h.version} · ${h.reviews.length} 条旧复核`),element('pre',h.text));for(const r of h.reviews)history.append(element('p',`${r.reviewer} / v${r.version}：${r.evidence}`));}body.append(history);}
    root.append(body);
    for(const other of files.filter(file=>file.id!==selectedFile)){const panel=element('div');panel.id=`file-panel-${other.id}`;panel.hidden=true;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',`file-tab-${other.id}`);root.append(panel);}
  }
  const past=state.files.filter(f=>f.revision!==state.revision);$('past-files').replaceChildren();
  if(past.length){const history=element('details');history.append(element('summary',`历史要求与原件 · ${past.length} 份`));for(const f of past)history.append(element('p',`目标 v${f.revision} / ${f.author} / 原件 v${f.version} / ${f.reviews.length} 条复核`),element('pre',f.text));$('past-files').append(history);}
}

function renderCoagents(){
  const active=!!state.instance?.active,files=currentFiles(),reviewCount=files.filter(reviewed).length;
  status('project-status',state.accepted?'已验收':ready(state)?'待你验收':state.revision?'协作进行中':'准备开始',state.accepted?'ready':state.revision?'progress':'');
  $('goal-version').textContent=state.revision?`v${state.revision}`:'未发布';$('file-count').textContent=`${files.length} / 2`;$('review-count').textContent=`${reviewCount} / 2`;
  $('binding-notice').classList.toggle('ready',active);
  $('binding-title').textContent=active?'演示实例已就绪':'先准备一位可用员工';
  $('binding-state').textContent=active?`${state.instance.executor} · 已绑定需求分析员，可以发布目标。`:'自动完成发布、部署、配置、ACK、规则检查与激活，逐步保留记录。';
  $('prepare-instance').hidden=active;$('publish-goal').disabled=!active;
  $('publish-goal').textContent=state.revision?'发布新要求并重新分工':'发布目标并分工';
  $('goal-summary').textContent=state.revision?`当前 v${state.revision} · 展开查看或修改`:'给团队一个明确的开始';
  $('document-caption').textContent=files.length?`${files.length} 份当前原件 · ${reviewCount} 份已复核`:'等待团队交稿';
  for(const [action,author] of [['draft-product','产品'],['draft-engineering','研发']])actionButton(action,!active||!state.revision||files.some(f=>f.author===author));
  status('delivery-badge',state.accepted?'已验收':ready(state)?'等待你的决定':files.length===2?'等待独立复核':'等待原件',state.accepted?'ready':ready(state)?'progress':'');
  $('delivery-state').textContent=state.accepted?`目标 v${state.revision} 的两份原件已接受。可以导出工作记录，或填写修改要求退回修订。`:ready(state)?`目标 v${state.revision} 的两份原件已有非作者复核，请阅读依据后作出验收决定。`:'团队交齐两份原件并完成独立复核后，由你决定是否接受。';
  $('acceptance-checks').replaceChildren();
  for(const author of ['产品','研发']){const file=files.find(f=>f.author===author),done=file&&reviewed(file),check=element('span',undefined,done?'done':'');check.append(element('i',done?'✓':''),element('span',`${author}原件${done?'已复核':file?'待复核':'待提交'}`));$('acceptance-checks').append(check);}
  actionButton('accept',!ready(state)||state.accepted);actionButton('return',!state.revision);$('export').disabled=!state.events.length;
  renderDocuments();
}

function render(){
  renderHelix();renderCoagents();
  const files=currentFiles(),count=state.accepted?4:files.length===2&&files.every(reviewed)?3:state.revision?2:state.instance?.active?1:0;
  $('sidebar-progress-label').textContent=['准备运行实例','公开目标与分工','制作与独立复核','等待人工验收','本次交付已接受'][count];
  $('sidebar-progress-count').textContent=`${count} / 4`;$('sidebar-progress-fill').style.width=`${count*25}%`;
  $('event-count').textContent=state.events.length;$('empty-events').hidden=!!state.events.length;
  $('events').replaceChildren(...[...state.events].reverse().map(e=>{const li=element('li');li.append(element('span',`操作 ${String(e.sequence).padStart(2,'0')}${e.revision?' / 目标 v'+e.revision:''}`,'event-meta'),element('span',e.message));return li;}));
}

function selectDocument(id,focus=false){selectedFile=id;renderDocuments();if(focus)$(`file-tab-${id}`).focus();}
document.addEventListener('click',e=>{
  const button=e.target.closest('button');if(!button)return;
  if(button.dataset.selectFile){selectDocument(Number(button.dataset.selectFile),true);return;}
  if(button.dataset.saveFile){const id=Number(button.dataset.saveFile);dispatch('edit',{id,text:$(`draft-${id}`).value});return;}
  const action=button.dataset.action;if(!action)return;
  if(action.startsWith('draft-'))dispatch('draft',{author:action==='draft-product'?'产品':'研发'});
  else dispatch(action,{executor:$('executor').value,evidence:$('acceptance').value});
});
document.addEventListener('input',e=>{
  const t=e.target;if(t.dataset.file){
    const id=Number(t.dataset.file),file=state.files.find(f=>f.id===id),unsaved=t.value!==file.text;edits.set(id,t.value);
    document.querySelector(`[data-save-file="${id}"]`).disabled=!unsaved;
    $('editor-hint').textContent=unsaved?'有未保存修改，保存后需要重新复核。':'修订会保留旧稿，并重新等待非作者复核。';$('editor-hint').classList.toggle('unsaved',unsaved);
  }
  if(t.dataset.reviewEvidence){const file=state.files.find(f=>f.id===Number(t.dataset.reviewEvidence));reviewDrafts.set(keyFor(file),t.value);}
});
document.addEventListener('change',e=>{if(e.target.dataset.reviewer){const file=state.files.find(f=>f.id===Number(e.target.dataset.reviewer));reviewers.set(keyFor(file),e.target.value);}});
document.addEventListener('submit',e=>{
  const form=e.target;
  if(form.id==='requirements-form'){e.preventDefault();dispatch('goal',{text:$('requirements').value});return;}
  if(form.dataset.reviewFile){
    e.preventDefault();const id=Number(form.dataset.reviewFile),file=state.files.find(f=>f.id===id);
    if($(`draft-${id}`).value!==file.text){feedback('请先保存原件修订，再对当前版本复核。',true);return;}
    const evidence=$(`review-evidence-${id}`).value,reviewer=$(`reviewer-${id}`).value;
    if(dispatch('review',{id,reviewer,evidence})){reviewDrafts.delete(keyFor(file));renderDocuments();}
  }
});
document.addEventListener('keydown',e=>{
  const tab=e.target.closest('[data-select-file]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const files=currentFiles(),index=files.findIndex(f=>f.id===Number(tab.dataset.selectFile));
  const next=e.key==='Home'?0:e.key==='End'?files.length-1:(index+(e.key==='ArrowRight'?1:-1)+files.length)%files.length;selectDocument(files[next].id,true);
});
$('prepare-instance').onclick=()=>{
  // Convenience action uses the same prerequisite-checked transitions and event log.
  if(!state.release&&!dispatch('publish'))return;
  if((!state.instance||state.instance.retired)&&!dispatch('deploy',{executor:$('executor').value}))return;
  for(const [action,key] of [['credentials','credentials'],['ack','ack'],['evaluate','evaluated'],['activate','active']])if(!state.instance[key]&&!dispatch(action))return;
  feedback('演示实例已就绪，可查看每一步的准备记录。');
};
$('reset').onclick=()=>$('reset-dialog').showModal();
$('reset-dialog').addEventListener('close',()=>{
  if($('reset-dialog').returnValue!=='reset')return;
  state=initial();selectedFile=null;edits.clear();reviewDrafts.clear();reviewers.clear();$('acceptance').value='';$('requirements').value='为一款家用阅读灯整理需求，面向夜间阅读，预算不超过 200 元；列出待确认问题。';$('executor').value='Codex';$('goal-panel').open=true;render();feedback('已重置，可以重新开始。');
});
$('dismiss-feedback').onclick=()=>$('feedback').hidden=true;
$('export').onclick=()=>{
  const data={kind:'synthetic-workflow-demo',baseline:'CoAgents 0.41.0 / HeliX multi-executor',...state};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=element('a');a.href=url;a.download='agent-workspace-demo.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
function view(scroll=false){
  const helix=new URLSearchParams(location.search).get('view')!=='coagents';document.body.dataset.view=helix?'helix':'coagents';
  $('helix').hidden=!helix;$('coagents').hidden=helix;
  for(const [id,active] of [['helix-tab',helix],['coagents-tab',!helix]]){if(active)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}
  $('topbar-product').textContent=helix?'HeliX / 员工实例':'CoAgents / 阅读灯需求评审';
  $('case-link').href=$('rail-case-link').href=helix?'../cases/helix.html':'../cases/coagents.html';
  document.title=helix?'HeliX · 数字员工运行台':'CoAgents · 数字同事工作室';
  if(scroll){window.scrollTo({top:0,behavior:'instant'});$('workspace').focus({preventScroll:true});}
}
for(const id of ['helix-tab','coagents-tab','open-coagents'])$(id).onclick=e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();history.pushState({},'',$(id).href);view(true);};
addEventListener('popstate',()=>view(true));
addEventListener('beforeunload',e=>{if(hasUnsaved()){e.preventDefault();e.returnValue='';}});
render();view();
