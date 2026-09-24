import {runCutout} from './cutout-job.mjs';
import {hasVisibleVariation} from './cutout-input.mjs';
const $=id=>document.getElementById(id);
let input,controller,output,previewURL,resultURL,selection=0,loading=false;
const status=t=>$('status').textContent=t;
function unlock(){controller=null;$('file').disabled=false;$('run').disabled=!input||loading;$('cancel').disabled=true;}
$('file').onchange=async()=>{
  const token=++selection,file=$('file').files[0]; if(!file)return;
  loading=true;$('run').disabled=true;status('正在读取图片…');
  try{
    if(!file.size||file.size>10*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('请选择非空且不超过 10 MB 的 PNG、JPEG 或 WebP。');
    const bitmap=await createImageBitmap(file);
    if(bitmap.width*bitmap.height>16e6){bitmap.close();throw Error('图片超过 1600 万像素。');}
    const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
    const canvas=document.createElement('canvas');canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();
    if(!hasVisibleVariation(canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data))throw Error('图片是纯色或完全透明，没有可区分的主体。请选择一张照片。');
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    if(token!==selection)return;if(!blob)throw Error('图片解码失败。');input=blob;output=null;
    URL.revokeObjectURL(previewURL);URL.revokeObjectURL(resultURL);previewURL=URL.createObjectURL(blob);$('before').src=previewURL;$('before').hidden=false;$('after').hidden=true;$('download').disabled=true;$('run').disabled=false;$('metrics').textContent=`处理尺寸 ${canvas.width} × ${canvas.height}`;status('图片已准备好。点击后才会下载模型。');
  }catch(error){if(token===selection)status(error.message+(input?' 保留上一张有效图片。':''));}
  finally{if(token===selection){loading=false;$('run').disabled=!input||!!controller;}}
};
$('run').onclick=async()=>{
  if(!input||controller||loading)return;const started=performance.now();controller=new AbortController();$('file').disabled=true;$('run').disabled=true;$('cancel').disabled=false;status('正在下载和准备模型…');
  try{
    const data=await runCutout({image:input,signal:controller.signal,createWorker:()=>new Worker('vendor/cutout-worker.bundle.js',{type:'module'}),onProgress:data=>status(data.key.startsWith('fetch:')?`下载模型资源：${Math.round(100*data.current/Math.max(1,data.total))}%（当前资源 ${(data.total/1048576).toFixed(1)} MiB）`:'正在计算前景与边缘…')});
    output=data.blob;URL.revokeObjectURL(resultURL);resultURL=URL.createObjectURL(output);$('after').src=resultURL;$('after').hidden=false;$('download').disabled=false;status(`完成，耗时 ${((performance.now()-started)/1000).toFixed(1)} 秒（含准备）。请核对边缘。`);
  }catch(error){status(error.message);}finally{unlock();}
};
$('cancel').onclick=()=>controller?.abort();
$('background').onchange=()=>{$('after').parentElement.style.background=$('background').value==='transparent'?'':$('background').value;};
$('download').onclick=()=>{if(!output)return;const a=document.createElement('a');a.href=resultURL;a.download='cutout-transparent.png';a.click();};
window.addEventListener('pagehide',()=>{controller?.abort();});
