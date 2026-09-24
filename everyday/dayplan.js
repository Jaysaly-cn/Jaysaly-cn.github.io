import {minute,clock,price,validate,individualIssues,schedule,plan,itineraryText,calendar} from './dayplan-core.mjs';
const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let sequence=0,worker=null,timer=null,settings=null,places=[],order=[],scores=new Map(),result=null;
const status=text=>$('status').textContent=text;
function stop(){worker?.terminate();worker=null;clearTimeout(timer);$('run').disabled=false;$('cancel').disabled=true;}
function reset(){stop();settings=null;places=[];order=[];scores=new Map();result=null;$('summary').replaceChildren();$('itinerary').replaceChildren();$('omitted').replaceChildren();$('omitted').hidden=true;$('txt').disabled=true;$('ics').disabled=true;status('条件已改变，旧安排已清空，请重新安排。');}
function addPlace(data={}){
 if($('places').children.length>=8){status('最多 8 个候选地点。');return;}
 const card=el('details',undefined,'place');card.dataset.id='place-'+(++sequence);card.dataset.synthetic=data.synthetic?'true':'false';card.open=!data.name;const summary=el('summary',data.name||'新候选地点 '+sequence);card.append(summary);
 function field(key,title,type,value){const label=el('label',title),input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.dataset.field=key;input.setAttribute('aria-label',`地点 ${sequence} ${title}`);input.value=data[key]??value??'';input.required=!['source'].includes(key);label.append(input);return {label,input};}
 const name=field('name','名称','text','');name.input.maxLength=60;name.input.addEventListener('input',()=>summary.textContent=name.input.value.trim()||'待填写的地点');
 const description=field('description','体验描述','textarea','');description.input.maxLength=180;card.append(name.label,description.label);
 const fields=el('div',undefined,'fields');
 for(const [key,title,type,value,min,max,step] of [['open','可访问开始','time','14:00'],['close','可访问结束','time','18:00'],['duration','停留分钟','number',60,5,480,1],['cost','预计花费（元）','number',0,0,100000,.01]]){
  const f=field(key,title,type,value);if(min!==undefined){f.input.min=min;f.input.max=max;f.input.step=step;}fields.append(f.label);
 }
 card.append(fields);const source=field('source','信息来源链接（可选）','url','');card.append(source.label);
 const required=el('label','必去', 'inline'),check=el('input');check.type='checkbox';check.dataset.field='required';check.checked=!!data.required;check.setAttribute('aria-label',`地点 ${sequence} 必去`);required.prepend(check);card.append(required);
 const remove=el('button','删除此候选','secondary');remove.type='button';remove.onclick=()=>{card.remove();reset();};card.append(remove);$('places').append(card);
}
function loadExample(){
 reset();$('places').replaceChildren();sequence=0;$('preference').value='想安静看书，喝咖啡，看看艺术展';$('start').value='14:00';$('end').value='18:00';$('budget').value='120';$('travel').value='20';$('max-stops').value='3';
 const examples=[['示例·书房','安静阅读、借阅书籍、室内学习','14:00','17:00',60,0],['示例·咖啡店','安静靠窗座位，手冲咖啡，读书休息','14:00','19:00',45,35],['示例·摄影展','室内摄影与艺术作品展览，慢慢欣赏','14:00','17:30',60,40],['示例·河畔步道','户外散步，看水边风景，轻松活动','14:00','19:00',50,0],['示例·周末市集','热闹逛街，体验小吃和手工摊位','15:00','18:30',60,50],['示例·攀岩馆','室内攀岩运动，挑战体能，活跃社交','14:00','19:00',60,80]];
 for(const [name,description,open,close,duration,cost] of examples)addPlace({name,description,open,close,duration,cost,synthetic:true});$('confirm-example').hidden=true;status('已填入 6 个虚构地点，仅用于演示计算流程；不是实际商家信息。');
}
function read(){
 const s={date:$('date').value,start:minute($('start').value),end:minute($('end').value),budget:Math.round(Number($('budget').value)*100),travel:Number($('travel').value),maxStops:Number($('max-stops').value),preference:$('preference').value.trim()};
 if(!s.preference)throw Error('请填写想要的体验。');
 const p=[...$('places').children].map(card=>{const get=key=>card.querySelector(`[data-field="${key}"]`);return {id:card.dataset.id,name:get('name').value.trim(),description:get('description').value.trim(),open:minute(get('open').value),close:minute(get('close').value),duration:Number(get('duration').value),cost:Math.round(Number(get('cost').value)*100),source:get('source').value.trim(),required:get('required').checked,synthetic:card.dataset.synthetic==='true'};});validate(s,p);for(const place of p)if(place.source)place.source=new URL(place.source).href;return {s,p};
}
function render(){
 result=schedule(order,settings,places);$('summary').replaceChildren();$('itinerary').replaceChildren();$('omitted').replaceChildren();
 $('summary').append(el('p',`${settings.date} · ${order.length} 站 · 预计 ${price(result.cost)} / 预算 ${price(settings.budget)}`));
 if(order.some(p=>p.synthetic))$('summary').append(el('p','包含虚构示例地点，仅用于测试规划，不是真实行程。','hint'));
 for(const issue of result.issues)$('summary').append(el('p',issue,'conflict'));
 if(order.length)$('summary').append(el('p',`首站默认开始时已可到达，站间统一预留 ${settings.travel} 分钟。营业和费用均待核实。`,'hint'));
 result.rows.forEach((r,index)=>{
  const box=el('article',undefined,'stop');box.append(el('p',`${clock(r.start)}–${clock(r.end)} · 等待 ${r.wait} 分钟`,'badge'),el('h3',r.name),el('p',r.description),el('p',`预计 ${price(r.cost)}${r.required?' · 必去':''}`));
  for(const issue of r.errors)box.append(el('p',issue,'conflict'));
  const actions=el('div',undefined,'actions');
  for(const [text,delta] of [['上移',-1],['下移',1]]){const button=el('button',text,'secondary');button.setAttribute('aria-label',text+' '+r.name);button.disabled=index+delta<0||index+delta>=order.length;button.onclick=()=>{[order[index],order[index+delta]]=[order[index+delta],order[index]];render();status('已重新检查调整后的安排。');};actions.append(button);}
  const remove=el('button','移除此站','secondary');remove.setAttribute('aria-label','移除 '+r.name);remove.onclick=()=>{order.splice(index,1);render();status('已移除并重新检查。');};actions.append(remove);box.append(actions);
  if(r.source){const link=el('a','核对用户填写的来源');link.href=r.source;link.target='_blank';link.rel='noopener';box.append(link);}else box.append(el('p','没有来源链接，请出发前核实。','hint'));
  const details=el('details');details.append(el('summary','查看偏好匹配参考'),el('p',`语义相关度 ${scores.get(r.id)?.toFixed(3)??'未计算'}，非喜欢概率；时间窗 ${clock(r.open)}–${clock(r.close)}。`));box.append(details);$('itinerary').append(box);
 });
 const omitted=places.filter(p=>!order.some(r=>r.id===p.id));$('omitted').hidden=!omitted.length;if(omitted.length)$('omitted').append(el('summary',`未纳入的 ${omitted.length} 个地点（可展开试排）`));
 for(const p of omitted){const box=el('div',undefined,'place'),reasons=individualIssues(p,settings);box.append(el('strong',p.name),el('p',reasons.join('；')||'在时间、预算、站数和偏好综合取舍中未纳入，可尝试加入后检查。'));const add=el('button','加入末尾','secondary');add.setAttribute('aria-label','加入末尾 '+p.name);add.disabled=order.length>=settings.maxStops;add.onclick=()=>{order.push(p);render();status('已加入并重新检查，请留意冲突。');};box.append(add);$('omitted').append(box);}
 $('txt').disabled=!result.valid;$('ics').disabled=!result.valid;
}
$('conditions').onsubmit=event=>{
 event.preventDefault();let input;try{input=read();}catch(error){status(error.message);return;}
 reset();settings=input.s;places=input.p;
 if(places.every(p=>individualIssues(p,settings).length)){render();status('没有地点能满足当前时间与预算，请查看原因。');return;}
 const current=new Worker('./vendor/semantic-worker.bundle.js',{type:'module'});worker=current;const started=performance.now();$('run').disabled=true;$('cancel').disabled=false;status('正在理解你的出行偏好…');
 const fail=message=>{if(worker!==current)return;stop();status(message+'，条件保留，可重试。');};timer=setTimeout(()=>fail('处理超过 8 分钟，已停止'),480000);
 current.onerror=()=>fail('语义引擎无法运行');current.onmessageerror=()=>fail('模型结果读取失败');
 current.onmessage=({data})=>{if(worker!==current)return;if(data.type==='progress')status(data.message);if(data.type==='error')fail('模型失败：'+data.message);if(data.type==='result'){try{const solution=plan(places,settings,data.scores);order=solution.order;scores=solution.scores;render();stop();status(order.length?`已安排 ${order.length} 站，耗时 ${((performance.now()-started)/1000).toFixed(1)} 秒（含准备）。可调整顺序后再导出。`:'没有能同时满足必去地点、时间和预算的安排。请调整条件。');}catch(error){fail(error.message);}}};
 current.postMessage({query:settings.preference,candidates:places.map(p=>({id:p.id,text:p.name+'。'+p.description}))});
};
$('conditions').addEventListener('input',()=>{if(worker||settings)reset();});
$('add-place').onclick=()=>{reset();addPlace();};
$('example').onclick=()=>{if([...document.querySelectorAll('[data-field=name]')].some(x=>x.value.trim()))$('confirm-example').hidden=false;else loadExample();};
$('replace-example').onclick=loadExample;$('keep-input').onclick=()=>{$('confirm-example').hidden=true;};
$('cancel').onclick=()=>{stop();status('已取消，输入保留，可重新安排。');};
function download(text,name,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('txt').onclick=()=>{if(result?.valid)download(itineraryText(result,settings),'dayplan.txt','text/plain;charset=utf-8');};
$('ics').onclick=()=>{if(!result?.valid)return;const stamp=new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'');download(calendar(result,settings,crypto.randomUUID(),stamp),'dayplan.ics','text/calendar;charset=utf-8');};
addEventListener('pagehide',stop);
const today=new Date();$('date').value=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;addPlace();
