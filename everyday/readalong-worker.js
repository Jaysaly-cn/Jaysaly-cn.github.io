import {pipeline,env} from '@huggingface/transformers';
env.allowLocalModels=false;
env.allowRemoteModels=true;
env.remoteHost='https://modelscope.cn/';
env.remotePathTemplate='models/{model}/resolve/{revision}/';
env.backends.onnx.wasm.numThreads=1;
env.backends.onnx.wasm.proxy=false;
self.onmessage=async({data})=>{
 try{
  const translate=await pipeline('translation','Xenova/opus-mt-en-zh',{revision:'563922a09e0e294a0f5785bffdaa758732da3714',device:'wasm',dtype:'q8',progress_callback:p=>self.postMessage({type:'progress',message:p.status==='progress'?`下载 ${p.file} · ${Math.round(p.progress)}%`:'正在准备翻译模型…'})});
  for(let i=0;i<data.parts.length;i++){
   self.postMessage({type:'progress',message:`正在翻译第 ${i+1}/${data.parts.length} 段…`});
   const result=await translate(data.parts[i],{max_new_tokens:256});
   self.postMessage({type:'part',index:i,text:result[0].translation_text});
  }
  self.postMessage({type:'done'});
  await translate.dispose();
 }catch(error){self.postMessage({type:'error',message:error.message});}
};
