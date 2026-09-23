let selected=null, materials=[], cards=[], busy=false;
const $=s=>document.querySelector(s);
function el(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function api(path,body){const r=await fetch('/api/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'输入未通过校验');return data;}
async function action(fn){if(busy)return;busy=true;try{await fn();await load();$('#notice').textContent='已保存。';}catch(e){$('#notice').textContent=e.message;}finally{busy=false;}}
function fields(form){return Object.fromEntries(new FormData(form));}
function choose(id){selected=id;const m=materials.find(x=>x.id===id);$('#selected').textContent=m.title;$('#body').textContent=m.body;$('#generate').disabled=false;}
async function load(){[materials,cards]=await Promise.all([api('materials'),api('cards')]);$('#sources').replaceChildren();for(const m of materials){const b=el('button',m.title);b.onclick=()=>choose(m.id);$('#sources').append(b);}if(selected)choose(selected);$('#drafts').replaceChildren();for(const card of cards.filter(x=>x.state==='draft')){const form=document.createElement('form');form.className='card';form.append(el('p',materials.find(x=>x.id===card.material_id)?.title));for(const [key,label] of [['question','问题'],['answer','答案'],['quote','原文引用']]){const l=el('label',label),input=document.createElement('textarea');input.name=key;input.value=card[key];input.required=true;l.append(input);form.append(l);}const check=document.createElement('input');check.type='checkbox';check.required=true;const label=el('label',' 我已核对问题、答案与引用');label.prepend(check);form.append(label,el('button','确认并加入复习'));form.onsubmit=e=>{e.preventDefault();action(()=>api('cards/'+card.id+'/approve',{...fields(form),version:card.version,checked:check.checked}));};$('#drafts').append(form);}if(!$('#drafts').children.length)$('#drafts').append(el('p','没有待确认卡片。'));renderLibrary();await queue();}
async function queue(){const due=await api('due');$('#queue').replaceChildren(el('p',`当前到期 ${due.length} 张 · 已确认 ${cards.filter(x=>x.state==='active').length} 张`));const card=due[0];if(!card){const next=cards.filter(x=>x.state==='active').sort((a,b)=>a.due.localeCompare(b.due))[0];$('#queue').append(el('p',next?'下次复习：'+new Date(next.due).toLocaleString():'暂无已启用的卡片。请先确认草稿。'));return;}const box=el('article','');box.append(el('p',materials.find(x=>x.id===card.material_id)?.title));const q=el('p',card.question);q.className='question';const flip=el('button','显示答案');box.append(q,flip);flip.onclick=()=>{flip.remove();const answer=el('div','');answer.className='answer';answer.append(el('p',card.answer),el('blockquote','原文：'+card.quote));['忘记','困难','记得','轻松'].forEach((label,i)=>{const b=el('button',label);b.onclick=()=>action(()=>api('cards/'+card.id+'/review',{version:card.version,rating:i+1}));answer.append(b);});box.append(answer);};$('#queue').append(box);}
$('#material').onsubmit=e=>{e.preventDefault();action(async()=>{const m=await api('materials',fields(e.target));selected=m.id;e.target.reset();});};
$('#manual').onsubmit=e=>{e.preventDefault();action(async()=>{if(!selected)throw Error('请先选择资料');await api('materials/'+selected+'/cards',fields(e.target));e.target.reset();});};
$('#generate').onclick=()=>action(async()=>{if(!selected)throw Error('请先选择资料');$('#notice').textContent='本地模型生成中，请稍候…';await api('materials/'+selected+'/generate',{});});
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{for(const id of ['make','review','library'])$('#'+id).hidden=id!==b.dataset.tab;if(b.dataset.tab==='review')load().catch(e=>$('#notice').textContent=e.message);});
$('#export').onclick=()=>action(async()=>{const data=await api('export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a','');a.href=url;a.download='studydeck-records.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
load().then(async()=>{$('#notice').textContent=(await api('status')).model_configured?'本地免费模型已连接。':'模型未配置，手工制卡和复习可用。';}).catch(e=>$('#notice').textContent=e.message);


function renderLibrary(){
 const query=$('#search').value.trim().toLowerCase();
 const states={draft:'待确认',active:'复习中',paused:'已暂停',rejected:'已拒绝'};
 $('#collection').replaceChildren();
 for(const card of cards){
  const title=materials.find(x=>x.id===card.material_id)?.title||'';
  if(!(card.question+' '+title).toLowerCase().includes(query))continue;
  const box=el('article','');box.append(el('p',title+' · '+states[card.state]),el('h2',card.question));
  if(card.due)box.append(el('p','计划时间：'+new Date(card.due).toLocaleString()));
  const choices={draft:['reject','拒绝草稿'],active:['pause','暂停复习'],paused:['resume','恢复复习'],rejected:['restore','恢复草稿']};
  const [command,label]=choices[card.state];const button=el('button',label);
  button.onclick=()=>action(()=>api('cards/'+card.id+'/transition',{version:card.version,action:command}));
  box.append(button);
  if(['active','paused'].includes(card.state)){
   const edit=el('button','修订内容');edit.onclick=()=>{
    edit.disabled=true;const form=document.createElement('form');
    form.append(el('p','修订后回到待确认，复习进度重新开始；旧内容和评分仍保留在导出记录中。'));
    form.append(el('blockquote','资料原文：'+(materials.find(x=>x.id===card.material_id)?.body||'')));
    for(const [key,label] of [['question','问题'],['answer','答案'],['quote','原文引用'],['note','修订原因（至少5字）']]){
     const field=el('label',label),input=document.createElement('textarea');input.name=key;input.value=card[key]||'';input.required=true;input.minLength=key==='note'?5:2;input.maxLength=key==='question'?500:key==='note'?1000:2000;field.append(input);form.append(field);
    }
    const cancel=el('button','取消');cancel.type='button';cancel.onclick=()=>{form.remove();edit.disabled=false;};
    form.append(el('button','保存修订并重新审核'),cancel);
    form.onsubmit=e=>{e.preventDefault();action(()=>api('cards/'+card.id+'/revise',{...fields(form),version:card.version}));};box.append(form);
   };box.append(edit);
  }
  $('#collection').append(box);
 }
 if(!$('#collection').children.length)$('#collection').append(el('p','没有匹配的卡片。'));
}
$('#search').oninput=renderLibrary;
