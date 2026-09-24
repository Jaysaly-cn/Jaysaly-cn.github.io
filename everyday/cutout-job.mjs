// A job owns its worker; late messages cannot affect a subsequent job.
export function runCutout({createWorker,image,signal,onProgress=()=>{},timeoutMs=180000}) {
  return new Promise((resolve,reject)=>{
    let worker,timer,done=false;
    function finish(error,result){
      if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);
      if(worker){worker.onmessage=null;worker.onerror=null;worker.onmessageerror=null;worker.terminate();}
      error?reject(error):resolve(result);
    }
    const abort=()=>finish(new DOMException('已取消，图片保留，可以重试。','AbortError'));
    if(signal?.aborted){abort();return;}
    signal?.addEventListener('abort',abort,{once:true});
    timer=setTimeout(()=>finish(new Error('处理超过 180 秒，已停止。可缩小图片后重试。')),timeoutMs);
    try{
      worker=createWorker();
      worker.onmessage=({data})=>{
        if(done)return;
        if(data.type==='progress')onProgress(data);
        if(data.type==='error')finish(new Error('模型处理失败：'+data.message));
        if(data.type==='result'){
          if(!(data.blob instanceof Blob)||!data.blob.size)finish(new Error('模型没有返回有效图片，请更换图片后重试。'));
          else finish(null,data);
        }
      };
      worker.onerror=()=>finish(new Error('引擎加载失败，请检查网络或浏览器支持后重试。'));
      worker.onmessageerror=()=>finish(new Error('处理结果传输失败，请重试。'));
      worker.postMessage({image});
    }catch(error){finish(error);}
  });
}
