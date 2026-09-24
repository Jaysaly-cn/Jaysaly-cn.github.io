import {audioStats,normalizeChunks,toSRT} from './clipscribe-core.mjs';
const $=id=>document.getElementById(id);let samples,duration,url,worker,timer,serial=0,segments=[],loading=false,dirty=false;
const status=text=>$('status').textContent=text;
function stop(){clearTimeout(timer);if(worker){worker.onmessage=null;worker.onerror=null;worker.terminate();worker=null;}$('file').disabled=false;$('language').disabled=false;$('run').disabled=!samples||loading;$('cancel').disabled=true;$('segments').querySelectorAll('input,textarea').forEach(el=>el.disabled=false);}
$('file').onchange=async()=>{
 const file=$('file').files[0],token=++serial;if(!file)return;loading=true;$('run').disabled=true;status('正在解码音频…');let context;
 try{
  if(!file.size||file.size>20*1024*1024)throw Error('请选择非空且不超过 20 MB 的音频。');
  context=new AudioContext();const decoded=await context.decodeAudioData(await file.arrayBuffer());
  if(decoded.duration>120||decoded.duration<0.1)throw Error('请使用 0.1 秒至 2 分钟的音频；超长文件不会被截断。');
  const offline=new OfflineAudioContext(1,Math.ceil(decoded.duration*16000),16000),source=offline.createBufferSource();source.buffer=decoded;source.connect(offline.destination);source.start();const buffer=await offline.startRendering();
  const data=buffer.getChannelData(0);if(audioStats(data).silent)throw Error('音频是静音或音量极低，请换一段清晰语音。');
  if(token!==serial)return;
  if(dirty&&!confirm('更换音频会清除当前修订，请先下载需要保留的字幕。继续吗？')){status('已取消更换，保留上一段音频与修订。');return;}
  samples=data;duration=decoded.duration;URL.revokeObjectURL(url);url=URL.createObjectURL(file);$('audio').src=url;$('pause').disabled=false;$('info').textContent=`${file.name} · ${duration.toFixed(1)} 秒`;segments=[];dirty=false;$('record').textContent='尚无转录记录。';$('segments').replaceChildren();$('srt').disabled=$('txt').disabled=true;status('音频已准备好，点击后才下载模型。');
 }catch(error){if(token===serial)status(error.message+(samples?' 保留上一段有效音频。':''));}
 finally{await context?.close();if(token===serial){loading=false;$('run').disabled=!samples||!!worker;}}
};
function render(){
 dirty=false;
 $('segments').replaceChildren();segments.forEach((s,i)=>{
  const row=document.createElement('section');row.className='segment';const play=document.createElement('button');play.className='secondary';play.textContent=`▶ 第 ${i+1} 段`;play.onclick=()=>{$('audio').currentTime=s.start;$('audio').play().catch(()=>status('请手动点击音频播放器播放。'));};row.append(play);
  const times=document.createElement('div');times.className='time-row';for(const [key,label]of [['start','开始秒数'],['end','结束秒数']]){const l=document.createElement('label');l.textContent=label;const input=document.createElement('input');input.type='number';input.min='0';input.max=String(duration);input.step='0.01';input.value=s[key].toFixed(2);input.oninput=()=>s[key]=input.value===''?NaN:Number(input.value);l.append(input);times.append(l);}row.append(times);
  const label=document.createElement('label');label.textContent=`第 ${i+1} 段文字${s.estimatedEnd?'（末端时间推定，请核对）':''}`;const text=document.createElement('textarea');text.value=s.text;text.oninput=()=>s.text=text.value;label.append(text);row.append(label);$('segments').append(row);
 });$('srt').disabled=$('txt').disabled=!segments.length;
}
$('run').onclick=()=>{
 if(!samples||worker||loading)return;if(segments.length&&!confirm('重新识别会替换当前修订的字幕，继续吗？'))return;
 $('file').disabled=$('language').disabled=$('run').disabled=true;$('cancel').disabled=false;status('正在准备模型…');const started=performance.now();
 $('segments').querySelectorAll('input,textarea').forEach(el=>el.disabled=true);
 try{const current=worker=new Worker('vendor/clipscribe-worker.bundle.js',{type:'module'});
 current.onmessage=({data})=>{if(worker!==current)return;if(data.type==='progress')status(data.message);if(data.type==='error'){status('识别失败：'+data.message+'。可重试。');stop();}if(data.type==='result'){try{$('record').textContent=JSON.stringify(data.result,null,2);segments=normalizeChunks(data.result.chunks,duration);render();const annotation=segments.some(s=>/^[（(\[].*[）)\]]$/.test(s.text));status(segments.length?`完成 ${segments.length} 段，耗时 ${((performance.now()-started)/1000).toFixed(1)} 秒（含准备）。${annotation?'结果包含疑似环境音描述，不能当作逐字人声字幕，请回听核对。':'请回听核对，模型可能漏字。'}`:'没有识别到文字，请检查音频或语言。');}catch(error){status(error.message);}finally{stop();}}};
 current.onerror=()=>{if(worker===current){status('语音引擎加载失败，请检查网络后重试。');stop();}};
 timer=setTimeout(()=>{stop();status('处理超过 5 分钟，已停止。请缩短音频后重试。');},300000);
 current.postMessage({audio:samples,language:$('language').value});
 }catch(error){status(error.message);stop();}
};
$('segments').addEventListener('input',()=>dirty=true);
$('cancel').onclick=()=>{stop();status('已取消，音频与之前的结果保留。');};
function download(content,extension){const u=URL.createObjectURL(new Blob(['\ufeff',content],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=u;a.download='clipscribe.'+extension;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
$('srt').onclick=()=>{try{download(toSRT(segments,duration),'srt');}catch(error){status(error.message);}};
$('txt').onclick=()=>download(segments.map(s=>s.text).join('\n'),'txt');
window.addEventListener('pagehide',stop);

$('pause').onclick=()=>$('audio').pause();
