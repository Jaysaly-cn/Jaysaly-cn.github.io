// One OCR operation owns one engine. Race every phase, not just recognition.
export async function runOCR({createWorker,image,signal,onReady=()=>{},onProgress=()=>{},timeoutMs=120000}){
 let worker,closed=false,timer,rejectStop;
 const stop=new Promise((_,reject)=>{rejectStop=reject;});
 const abort=()=>rejectStop(Error('已取消本次识别，图片保留，可重新开始。'));
 const release=async w=>{try{await w.terminate();}catch{}};
 const deadline=()=>rejectStop(Error('本次处理超过 120 秒。请检查网络，或换更小图片后重试。'));
 try{
  if(signal?.aborted)throw Error('已取消本次识别。');
  signal?.addEventListener('abort',abort,{once:true});
  timer=setTimeout(deadline,timeoutMs);
  const pending=Promise.resolve().then(()=>createWorker({
   logger:message=>{if(!closed)onProgress(message);},
   errorHandler:error=>rejectStop(error instanceof Error?error:Error(String(error)))
  }));
  pending.then(w=>{if(closed)void release(w);},()=>{});
  worker=await Promise.race([pending,stop]);
  onReady();
  await Promise.race([worker.setParameters({tessedit_pageseg_mode:'3'}),stop]);
  return await Promise.race([worker.recognize(image),stop]);
 }finally{
  closed=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);
  if(worker)await release(worker);
 }
}
