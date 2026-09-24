import {splitReading,bilingualText} from './readalong-core.mjs';
const $=id=>document.getElementById(id);
let worker=null,timer=null,parts=[],dirty=false;
const savedKey='everyday-readalong-notes-v1';
const notesBox=document.createElement('section');notesBox.className='panel';notesBox.innerHTML='<h2>随手词语笔记</h2><p class="hint">自行记录词语和理解；点击保存后才存入此浏览器，最多 50 条。不是自动词典释义。</p><label>英文词语或短语<input id="word" maxlength="120"></label><label>我的理解<input id="meaning" maxlength="500"></label><div class="actions"><button id="save-note">保存笔记到本机</button><button id="export-notes" class="secondary">导出笔记</button></div><p id="note-status" role="status"></p><div id="notes"></div>';
document.querySelector('main').append(notesBox);
let notes=[];
try{const stored=JSON.parse(localStorage.getItem(savedKey)||'[]');if(Array.isArray(stored))notes=stored.filter(n=>typeof n.word==='string'&&typeof n.meaning==='string').slice(0,50);}catch{ $('note-status').textContent='无法读取本机笔记；仍可临时记录和导出。'; }
function download(text,name){const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function persistNotes(){try{localStorage.setItem(savedKey,JSON.stringify(notes));$('note-status').textContent='笔记已保存到此浏览器。';}catch{$('note-status').textContent='本机存储不可用；笔记仅临时保留，请导出备份。';}renderNotes();}
function renderNotes(){ $('notes').replaceChildren();notes.forEach((n,i)=>{const row=document.createElement('div');row.className='reading-part';const text=document.createElement('p');text.className='original';text.textContent=n.word+' — '+n.meaning;const remove=document.createElement('button');remove.className='secondary';remove.textContent='移除第 '+(i+1)+' 条';remove.onclick=()=>{notes.splice(i,1);persistNotes();};row.append(text,remove);$('notes').append(row);});$('export-notes').disabled=!notes.length;}
$('save-note').onclick=()=>{const word=$('word').value.trim(),meaning=$('meaning').value.trim();if(!word||!meaning){$('note-status').textContent='请填写词语和自己的理解。';return;}if(notes.length>=50){$('note-status').textContent='已达 50 条，请先导出并整理。';return;}notes.push({word,meaning});persistNotes();$('word').value='';$('meaning').value='';};
$('export-notes').onclick=()=>download(notes.map(n=>n.word+'\n'+n.meaning).join('\n\n'),'readalong-notes.txt');
renderNotes();
function status(text){$('status').textContent=text;}
function finish(){worker?.terminate();worker=null;clearTimeout(timer);$('run').disabled=false;$('input').disabled=false;$('cancel').disabled=true;document.querySelectorAll('#parts textarea').forEach(el=>el.disabled=false);$('download').disabled=!parts.some(p=>p.translation);}
function render(){
 $('parts').replaceChildren();
 parts.forEach((part,i)=>{
  const section=document.createElement('section');section.className='reading-part';
  const original=document.createElement('p');original.className='original';original.lang='en';original.textContent=`${i+1}. ${part.source}`;
  const state=document.createElement('span');state.className='tag';state.textContent=part.translation?'已生成，可核对':'尚未生成';section.append(state);
  const label=document.createElement('label');label.textContent=`第 ${i+1} 段中文译文`;
  const edit=document.createElement('textarea');edit.value=part.translation;edit.disabled=!!worker;edit.placeholder='等待翻译';edit.addEventListener('input',()=>{part.translation=edit.value;dirty=true;$('download').disabled=!parts.some(p=>p.translation);});label.append(edit);section.append(original,label);$('parts').append(section);
 });
}
const replaceBox=document.createElement('div');replaceBox.hidden=true;replaceBox.className='status';replaceBox.innerHTML='<p>重新翻译将替换已修订译文。请先下载需要保留的笔记。</p><div class="actions"><button id="replace-confirm">替换并翻译</button><button id="replace-cancel" class="secondary">保留修订</button></div>';$('run').parentElement.after(replaceBox);
let pendingSource=null;
$('replace-cancel').onclick=()=>{replaceBox.hidden=true;pendingSource=null;};
$('replace-confirm').onclick=()=>{replaceBox.hidden=true;const source=pendingSource;pendingSource=null;if(source)start(source);};
$('run').onclick=()=>{
 let source;try{source=splitReading($('input').value);}catch(e){status(e.message);return;}
 if(dirty){pendingSource=source;replaceBox.hidden=false;return;}
 start(source);
};
function start(source){
 finish();parts=source.map(source=>({source,translation:''}));dirty=false;
 const start=performance.now();const current=new Worker('./vendor/readalong-worker.bundle.js',{type:'module'});worker=current;
 $('run').disabled=true;$('input').disabled=true;$('cancel').disabled=false;$('download').disabled=true;render();status('正在准备模型…');
 timer=setTimeout(()=>{if(worker===current){finish();status('处理超过 8 分钟，已停止；已完成段落仍可导出。请缩短原文后重试。');}},480000);
 current.onmessage=({data})=>{
  if(worker!==current)return;
  if(data.type==='progress')status(data.message);
  if(data.type==='part'){parts[data.index].translation=data.text;render();}
  if(data.type==='done'){finish();status(`完成 ${parts.length} 段，耗时 ${((performance.now()-start)/1000).toFixed(1)} 秒（含准备）。请核对并修订译文。`);}
  if(data.type==='error'){finish();status('翻译失败：'+data.message+'。已完成段落保留，可重试。');}
 };
 current.onerror=()=>{if(worker===current){finish();status('翻译引擎未能运行，请检查网络或减少文本后重试。');}};
 current.onmessageerror=()=>{if(worker===current){finish();status('未能读取翻译结果，已停止；可保留已完成段落后重试。');}};
 current.postMessage({parts:source});
}
$('cancel').onclick=()=>{finish();status('已取消。已完成段落保留，可修订和导出。');};
$('download').onclick=()=>download(bilingualText(parts),'readalong.txt');
addEventListener('pagehide',finish);
