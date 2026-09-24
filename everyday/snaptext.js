import {runOCR} from './ocr-job.mjs';
import {validateFile,dimensions,txtName,recognitionRecord} from './snaptext-core.mjs';
const $=s=>document.querySelector(s);
let canvas=null,name='snaptext',raw='',record=null,busy=false,ready=false,controller=null,selection=0;
const say=text=>{$('#status').textContent=text;};
function buttons(){$('#result').readOnly=busy;for(const id of ['file','sample','rotate','language','clear'])$('#'+id).disabled=busy||(id==='rotate'&&!canvas);$('#recognize').disabled=busy||!canvas;$('#cancel').disabled=!busy||!ready;for(const id of ['copy','download'])$('#'+id).disabled=!$('#result').value.trim();$('#original').disabled=busy||!raw;}
function showImage(next,fileName){canvas=next;name=fileName;$('#preview').src=canvas.toDataURL('image/png');$('#preview').hidden=false;$('#empty').hidden=true;$('#dimensions').textContent=`处理尺寸 ${canvas.width} × ${canvas.height}`;raw='';record=null;$('#result').value='';$('#record').textContent='还没有识别记录。';$('#metrics').textContent='';$('#progress').value=0;buttons();}
async function loadFile(file){if(busy)return;const current=++selection;try{validateFile(file);const bitmap=await createImageBitmap(file,{imageOrientation:'from-image'});try{const size=dimensions(bitmap.width,bitmap.height);if(current!==selection||busy)return;if($('#result').value&&!confirm('替换图片会清空当前识别结果，请先复制或下载。继续吗？'))return;const next=document.createElement('canvas');next.width=size.width;next.height=size.height;const ctx=next.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,next.width,next.height);ctx.drawImage(bitmap,0,0,next.width,next.height);showImage(next,file.name);say(size.scaled?'已等比缩小到最长边 2500 像素，可开始识别。':'图片已准备好，选择语言后提取文字。');}finally{bitmap.close();}}catch(e){say(e.message||'无法解码这张图片，请重新选择。');}}
$('#file').onchange=e=>{if(e.target.files[0])loadFile(e.target.files[0]);e.target.value='';};
document.addEventListener('paste',e=>{const image=[...(e.clipboardData?.items||[])].find(item=>item.type.startsWith('image/'));if(image&&!busy){e.preventDefault();const f=image.getAsFile();if(f)loadFile(f);}});
$('#sample').onclick=()=>{if($('#result').value&&!confirm('示例会清空当前结果，继续吗？'))return;selection++;const c=document.createElement('canvas');c.width=1200;c.height=400;const ctx=c.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle='#111';ctx.font='42px "Microsoft YaHei",sans-serif';ctx.fillText('周末出行清单',50,85);ctx.fillText('带上水杯和雨伞，下午三点出发。',50,170);ctx.font='38px Arial,sans-serif';ctx.fillText('Weekend plan: bring water. Leave at 15:00.',50,255);ctx.fillText('Reference: A2026-0924',50,330);showImage(c,'synthetic-weekend.png');say('这是一张现场绘制的测试图片。点击提取文字，运行真实 OCR。');};
$('#rotate').onclick=()=>{if(!canvas||busy)return;if($('#result').value&&!confirm('旋转后需要重新识别，清空当前结果吗？'))return;const c=document.createElement('canvas');c.width=canvas.height;c.height=canvas.width;const ctx=c.getContext('2d');ctx.translate(c.width,0);ctx.rotate(Math.PI/2);ctx.drawImage(canvas,0,0);showImage(c,name);say('已顺时针旋转 90°。');};
$('#clear').onclick=()=>{if(busy)return;if($('#result').value&&!confirm('清空图片和结果？未下载内容无法恢复。'))return;selection++;canvas=null;raw='';record=null;$('#preview').removeAttribute('src');$('#preview').hidden=true;$('#empty').hidden=false;$('#result').value='';$('#metrics').textContent=$('#dimensions').textContent='';$('#record').textContent='还没有识别记录。';$('#progress').value=0;say('已清空，等待新图片。');buttons();};
$('#recognize').onclick=async()=>{
 if(busy||!canvas)return;
 if($('#result').value&&$('#result').value!==raw&&!confirm('重新识别会替换已编辑文字，继续吗？'))return;
 selection++;busy=true;buttons();$('#progress').value=0;say('正在准备识别引擎与语言模型，首次下载可能需要稍等…');
 const started=performance.now(),language=$('#language').value;
 controller=new AbortController();ready=false;
 try{
  if(!window.Tesseract)throw Error('识别引擎未载入，请刷新页面后重试。');
  const result=await runOCR({image:canvas,signal:controller.signal,onReady:()=>{ready=true;buttons();},
   createWorker:handlers=>Tesseract.createWorker(language,1,{workerPath:new URL('vendor/worker.min.js',location.href).href,corePath:new URL('vendor/core/',location.href).href,langPath:new URL('vendor/lang',location.href).href,workerBlobURL:false,...handlers}),
   onProgress:m=>{const labels={'loading tesseract core':'载入识别引擎','initializing tesseract':'准备识别引擎','loading language traineddata':'载入语言模型','initializing api':'准备语言模型','recognizing text':'正在识别文字'};if(labels[m.status])say(labels[m.status]+(Number.isFinite(m.progress)?` · ${Math.round(m.progress*100)}%`:''));if(m.status==='recognizing text')$('#progress').value=m.progress;}
  });
  raw=result.data.text;record=recognitionRecord({name,language,text:raw,confidence:result.data.confidence,elapsed:performance.now()-started,width:canvas.width,height:canvas.height});
  $('#result').value=raw;$('#metrics').textContent=`${record.characters} 字符 · ${(record.elapsedMs/1000).toFixed(1)} 秒（含准备） · 引擎置信度 ${record.confidence??'未知'}，不是准确率`;
  $('#record').textContent=JSON.stringify(record,null,2);$('#progress').value=1;say(raw.trim()?'识别完成，请核对姓名、数字和日期，再复制或下载。':'未检测到可读文字。请换清晰图片，或旋转后重试。');
 }catch(e){say(e.message||'识别失败。请检查网络和图片格式后重试。');}
 finally{controller=null;ready=false;busy=false;buttons();}
};
$('#cancel').onclick=()=>controller?.abort();
$('#result').oninput=buttons;
$('#copy').onclick=async()=>{try{await navigator.clipboard.writeText($('#result').value);say('已复制当前编辑后的文字。');}catch{$('#result').select();say('无法自动复制，文字已选中，请使用系统复制。');}};
$('#download').onclick=()=>{const blob=new Blob(['\ufeff'+$('#result').value],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=txtName(name);a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);say('已导出当前编辑后的文字。');};
$('#original').onclick=()=>{if($('#result').value!==raw&&!confirm('恢复识别原文会丢弃手动修改，继续吗？'))return;$('#result').value=raw;buttons();say('已恢复本次引擎识别原文。');};
buttons();
