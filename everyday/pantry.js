import {tokens,inspectRecipe,rankRecipes,amounts,amountText,shoppingList} from './pantry-core.mjs';
const $=id=>document.getElementById(id);
const el=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
let recipes=[],worker=null,timer=null,settings=null,selected=new Set(),ranked=[];
const status=text=>$('status').textContent=text;
function stop(){worker?.terminate();worker=null;clearTimeout(timer);$('run').disabled=!recipes.length;$('cancel').disabled=true;}
function reset(){stop();selected.clear();ranked=[];settings=null;$('results').replaceChildren();$('filtered').hidden=true;renderPlan();status('条件已改变，旧结果已清空，请重新推荐。');}
function readSettings(){
 const inventory=tokens($('inventory').value),excluded=tokens($('excluded').value),tools=[...document.querySelectorAll('[name=tool]:checked')].map(x=>x.value);
 if(!inventory.length)throw Error('请至少填写一种已有食材。');
 if(!tools.length)throw Error('请至少选择一种可用厨具。');
 const factor=Number($('factor').value),maxTime=Number($('time').value);if(!Number.isInteger(factor)||factor<1||factor>4||!Number.isFinite(maxTime))throw Error('份数或时间无效。');
 return {inventory,excluded,tools,factor,maxTime,includeOptional:$('optional').checked,query:$('preference').value.trim()||'简单好做的家常菜'};
}
function renderResults(){
 $('results').replaceChildren();
 for(const row of ranked){
  const r=row.recipe,box=el('article',undefined,'recipe');box.append(el('h3',r.name),el('p',r.description));
  box.append(el('p',`预估 ${r.minutes} 分钟 / ${r.tools.join('、')} / ${r.portion}`,'meta'));
  box.append(el('p',`食材种类覆盖 ${Math.round(row.coverage*100)}% · AI 语义相关度 ${row.semantic.toFixed(3)}（非准确率）`,'meta'));
  box.append(el('p',row.missing.length?'缺少：'+row.missing.map(i=>i.name).join('、'):'所列必需材料均填写为已有；请另核对数量。'));
  const label=el('label','加入这一餐'),check=el('input');check.type='checkbox';check.checked=selected.has(r.id);check.setAttribute('aria-label','加入 '+r.name);check.style.width='auto';label.prepend(check);
  check.onchange=()=>{if(check.checked&&selected.size>=4){check.checked=false;status('一餐最多选择 4 道菜，请先移除一道。');return;}check.checked?selected.add(r.id):selected.delete(r.id);renderPlan();};box.append(label);
  const details=el('details');details.append(el('summary','查看备料与原方步骤'));const list=el('ul');
  for(const i of r.ingredients){if(i.optional&&!settings.includeOptional)continue;list.append(el('li',`${i.name}：${amountText(amounts(i,settings.factor,r))}${i.optional?'（可选）':''}`));}
  details.append(el('p',`当前按 ${settings.factor} 份原配方备料。`),list);
  for(const note of r.notes)details.append(el('p',note,'hint'));
  details.append(el('p','以下是原方步骤，数字仍为原方示例量；请对照上方备料表调整用量，时间与火候不可简单倍增。','hint'),el('pre',r.instructions,'source-steps'));
  const source=el('a','查看固定版本原文');source.href=r.source;source.target='_blank';source.rel='noopener';details.append(source);box.append(details);$('results').append(box);
 }
}
function mealRecipes(){return ranked.filter(x=>selected.has(x.recipe.id)).map(x=>x.recipe);}
function shoppingText(item){return item.name+'：'+(item.unknown?(item.max?amountText(item)+'，另有未定量部分':'原方未定量，需核对'):amountText(item));}
function renderPlan(){
 const list=mealRecipes();$('plan').replaceChildren();$('download').disabled=!list.length;
 if(!list.length){$('plan').append(el('p','从推荐中加入菜品，最多 4 道。'));return;}
 $('plan').append(el('p',`已选 ${list.map(r=>r.name).join('、')}；每道 ${settings.factor} 份原配方。按逐道、逐批相加约 ${list.reduce((sum,r)=>sum+r.minutes,0)*settings.factor} 分钟，仅用于粗略预算。`));
 $('plan').append(el('p','已有（仅检查有无）：'+settings.inventory.join('、'),'hint'));
 const shopping=shoppingList(list,settings),ul=el('ul');
 for(const item of shopping)ul.append(el('li',shoppingText(item)+' · 用于 '+item.recipes.join('、')));
 $('plan').append(el('h3','缺料采购清单'),shopping.length?ul:el('p','没有缺少的材料种类；请检查库存数量。'));
}
function exportPlan(){
 const list=mealRecipes(),shopping=shoppingList(list,settings);
 const text=['今晚吃什么 · 一餐计划',`每道 ${settings.factor} 份原配方；不是统一人数。`,`偏好：${settings.query}`,`已有食材（未核对余量）：${settings.inventory.join('、')}`,`排除项：${settings.excluded.join('、')||'无'}`,'','缺料采购清单',...shopping.map(shoppingText),'',...list.flatMap(r=>[r.name+' / '+r.portion,...r.ingredients.filter(i=>settings.includeOptional||!i.optional).map(i=>`${i.name}：${amountText(amounts(i,settings.factor,r))}`),...r.notes,'原方步骤（示例量未换算，请对照备料表调整，火候不可简单倍增）：',r.instructions,'来源：'+r.source,''])].join('\n');
 const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=el('a');a.href=url;a.download='pantry-plan.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('conditions').onsubmit=event=>{
 event.preventDefault();let next;try{next=readSettings();}catch(error){status(error.message);return;}
 stop();settings=next;selected.clear();ranked=[];$('results').replaceChildren();renderPlan();
 const inspected=recipes.map(r=>inspectRecipe(r,settings)),eligible=inspected.filter(x=>!x.reasons.length);
 $('rejected').replaceChildren();for(const row of inspected.filter(x=>x.reasons.length))$('rejected').append(el('li',row.recipe.name+'：'+row.reasons.join('；')));$('filtered').hidden=!$('rejected').children.length;
 if(!eligible.length){status('没有符合这些条件的菜谱。请查看未纳入原因，或调整食材和厨具条件。');return;}
 const current=new Worker('./vendor/semantic-worker.bundle.js',{type:'module'});worker=current;const start=performance.now();$('run').disabled=true;$('cancel').disabled=false;status('正在准备语义模型…');
 const fail=message=>{if(worker!==current)return;stop();status(message+'，请检查网络后重试。');};
 timer=setTimeout(()=>fail('处理超过 8 分钟，已停止'),480000);
 current.onerror=()=>fail('语义引擎无法运行');current.onmessageerror=()=>fail('模型结果读取失败');
 current.onmessage=({data})=>{if(worker!==current)return;if(data.type==='progress')status(data.message);if(data.type==='error')fail('模型失败：'+data.message);if(data.type==='result'){try{ranked=rankRecipes(inspected,data.scores);stop();renderResults();status(`找到 ${ranked.length} 道候选，耗时 ${((performance.now()-start)/1000).toFixed(1)} 秒（含准备）。先查看用量，再加入这一餐。`);}catch(error){fail(error.message);}}};
 current.postMessage({query:settings.query,candidates:eligible.map(x=>({id:x.recipe.id,text:x.recipe.name+'。'+x.recipe.description}))});
};
$('conditions').addEventListener('input',()=>{if(worker||ranked.length||settings)reset();});
$('cancel').onclick=()=>{stop();status('已取消，条件保留，可重试。');};$('download').onclick=exportPlan;
addEventListener('pagehide',stop);
$('run').disabled=true;
fetch('./data/recipes.json').then(r=>{if(!r.ok)throw Error('菜谱资源不可用');return r.json();}).then(data=>{recipes=data.recipes;$('run').disabled=false;status(`已载入 ${recipes.length} 道有来源的菜谱，填写条件后开始。`);}).catch(error=>status('加载失败：'+error.message+'。请刷新重试。'));


