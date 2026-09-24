export function minute(value){if(!/^\d{2}:\d{2}$/.test(value))throw Error('时间请使用 HH:MM。');const [h,m]=value.split(':').map(Number);if(h>23||m>59)throw Error('时间超出当天范围。');return h*60+m;}
export const clock=n=>`${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;
export const price=n=>`¥${(n/100).toFixed(2)}`;
function integer(value,min,max,label){if(!Number.isInteger(value)||value<min||value>max)throw Error(`${label}须在 ${min}–${max} 之间。`);}
export function validate(settings,places){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(settings.date)||!Number.isFinite(Date.parse(settings.date+'T00:00:00Z'))||new Date(settings.date+'T00:00:00Z').toISOString().slice(0,10)!==settings.date)throw Error('请选择有效日期。');
 integer(settings.start,0,1439,'开始时间');integer(settings.end,0,1439,'结束时间');if(settings.start>=settings.end)throw Error('首版只安排同一天，结束时间必须晚于开始时间。');
 integer(settings.budget,0,10000000,'预算分值');integer(settings.travel,0,120,'转场分钟');integer(settings.maxStops,1,4,'最多地点数');
 if(places.length<1||places.length>8)throw Error('请填写 1–8 个候选地点。');
 const ids=new Set(),names=new Set();
 for(const p of places){
  if(!p.name.trim()||p.name.length>60||!p.description.trim()||p.description.length>180)throw Error('每个地点都需要名称（最多 60 字）和体验描述（最多 180 字）。');
  if(ids.has(p.id)||names.has(p.name.trim().toLowerCase()))throw Error('地点名称不能重复。');ids.add(p.id);names.add(p.name.trim().toLowerCase());
  integer(p.open,0,1439,'可访问开始时间');integer(p.close,0,1439,'可访问结束时间');if(p.open>=p.close)throw Error(`${p.name} 的时间窗须在同一天且结束晚于开始。`);
  integer(p.duration,5,480,'停留分钟');integer(p.cost,0,10000000,'花费分值');
  if(p.source){let url;try{url=new URL(p.source);}catch{throw Error(`${p.name} 的来源链接无效。`);}if(!['http:','https:'].includes(url.protocol)||/[\r\n]/.test(p.source))throw Error('来源仅支持 HTTP/HTTPS 网页。');}
 }
 if(places.filter(p=>p.required).length>settings.maxStops)throw Error('必去地点超过最多停靠数，请调整。');
}
export function individualIssues(p,s){const issues=[];if(Math.max(s.start,p.open)+p.duration>Math.min(s.end,p.close))issues.push('停留时间无法放进可访问时间窗');if(p.cost>s.budget)issues.push('单点预计花费已超预算');return issues;}
export function schedule(order,settings,allPlaces=order){
 let time=settings.start,cost=0;const rows=[],issues=[];
 for(const [index,p] of order.entries()){
  const arrival=time+(index?settings.travel:0),start=Math.max(arrival,p.open),end=start+p.duration,errors=[];cost+=p.cost;
  if(end>p.close)errors.push('超过该地点可访问时间');if(end>settings.end)errors.push('超过当天结束时间');
  rows.push({...p,arrival,start,end,wait:start-arrival,errors});time=end;
 }
 if(!order.length)issues.push('尚无地点');if(order.length>settings.maxStops)issues.push('超过最多停靠数');if(cost>settings.budget)issues.push(`预计花费 ${price(cost)} 超过预算 ${price(settings.budget)}`);
 const missing=allPlaces.filter(p=>p.required&&!order.some(x=>x.id===p.id));if(missing.length)issues.push('遗漏必去：'+missing.map(p=>p.name).join('、'));
 return {rows,issues,cost,end:time,valid:issues.length===0&&rows.every(r=>!r.errors.length)};
}
export function plan(places,settings,scores){
 validate(settings,places);const scoreMap=new Map(scores.map(x=>[x.id,x.score]));
 if(places.some(p=>!Number.isFinite(scoreMap.get(p.id))))throw Error('偏好匹配结果不完整，请重试。');
 let best=null,visited=0;
 function search(order,remaining,time,cost,value){
  visited++;
  const requiredOK=places.every(p=>!p.required||order.some(x=>x.id===p.id));
  if(order.length&&requiredOK&&(!best||value>best.value+1e-8||(Math.abs(value-best.value)<1e-8&&(time<best.end||(time===best.end&&cost<best.cost)))))best={order:[...order],value,end:time,cost};
  if(order.length>=settings.maxStops)return;
  for(const p of remaining){const start=Math.max(time+(order.length?settings.travel:0),p.open),end=start+p.duration;
   if(end>Math.min(p.close,settings.end)||cost+p.cost>settings.budget)continue;
   search([...order,p],remaining.filter(x=>x.id!==p.id),end,cost+p.cost,value+Math.max(0,scoreMap.get(p.id)));
  }
 }
 search([],places,settings.start,0,0);
 return {order:best?.order||[],visited,scores:scoreMap};
}
export function itineraryText(result,s){return [`周末半径 · ${s.date}`,`当天 ${clock(s.start)}–${clock(s.end)}；预算 ${price(s.budget)}；预计花费 ${price(result.cost)}`,`每次转场预留 ${s.travel} 分钟（用户假设，非地图路线）；首站默认从当天起始时刻已可到达。`,'',...result.rows.flatMap((r,i)=>[`${i+1}. ${clock(r.start)}–${clock(r.end)} ${r.name}`,`等待 ${r.wait} 分钟；预计 ${price(r.cost)}；${r.description}`,(r.synthetic?'虚构示例，仅用于测试。':'')+(r.source?'待核实来源：'+r.source:'没有来源链接：出发前核实营业时间与花费。'),...r.errors.map(x=>'冲突：'+x),'']),...result.issues.map(x=>'冲突：'+x),'出发前核对：营业时间、预约/票价、每段实际路程和天气。模型不查询实时信息。'].join('\n');}
const escapeICS=s=>s.replace(/\\/g,'\\\\').replace(/\r\n|\r|\n/g,'\\n').replace(/;/g,'\\;').replace(/,/g,'\\,');
export function fold(line){let out=[],part='',bytes=0;for(const char of line){const n=new TextEncoder().encode(char).length;if(bytes+n>75){out.push(part);part=' ';bytes=1;}part+=char;bytes+=n;}out.push(part);return out.join('\r\n');}
export function calendar(result,s,uid,stamp){
 if(!result.valid)throw Error('请先解决日程冲突再导出日历。');
 const when=n=>s.date.replaceAll('-','')+'T'+clock(n).replace(':','')+'00';
 const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Everyday AI//DayPlan//ZH','CALSCALE:GREGORIAN'];
 for(const [i,r] of result.rows.entries()){
  lines.push('BEGIN:VEVENT',`UID:${i}-${uid}@everyday.local`,`DTSTAMP:${stamp}`,`DTSTART:${when(r.start)}`,`DTEND:${when(r.end)}`,'SUMMARY:'+escapeICS(r.name),'DESCRIPTION:'+escapeICS(`${r.synthetic?'虚构示例，仅用于测试。':''}预计 ${price(r.cost)}。${r.description}\n营业与费用待核实。${r.source||'无来源链接。'}\n按导入日历的本地时间使用。`));
  if(r.source)lines.push('URL:'+r.source);lines.push('END:VEVENT');
 }
 lines.push('END:VCALENDAR');return lines.map(fold).join('\r\n')+'\r\n';
}
