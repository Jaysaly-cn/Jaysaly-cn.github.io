import {pipeline,env} from '@huggingface/transformers';
env.allowLocalModels=true;
env.allowRemoteModels=false;
env.localModelPath=new URL('./models/',import.meta.url).href;
env.backends.onnx.wasm.numThreads=1;
env.backends.onnx.wasm.proxy=false;
self.onmessage=async({data})=>{
 try{
  const transcriber=await pipeline('automatic-speech-recognition','onnx-community/whisper-tiny',{device:'wasm',dtype:'q8',progress_callback:p=>self.postMessage({type:'progress',message:p.status==='progress'?`下载 ${p.file} · ${Math.round(p.progress)}%`:'正在准备语音模型…'})});
  self.postMessage({type:'progress',message:'正在识别语音，请稍候…'});
  const result=await transcriber(data.audio,{language:data.language,task:'transcribe',return_timestamps:true,chunk_length_s:20,stride_length_s:3});
  self.postMessage({type:'result',result});
  await transcriber.dispose();
 }catch(error){self.postMessage({type:'error',message:error.message});}
};
