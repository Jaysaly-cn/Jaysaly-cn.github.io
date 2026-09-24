import {pipeline,env} from '@huggingface/transformers';
env.allowLocalModels=false;
env.allowRemoteModels=true;
env.remoteHost='https://modelscope.cn/';
env.remotePathTemplate='models/{model}/resolve/{revision}/';
env.backends.onnx.wasm.numThreads=1;
env.backends.onnx.wasm.proxy=false;
self.onmessage=async({data})=>{
 try{
  const embed=await pipeline('feature-extraction','Xenova/paraphrase-multilingual-MiniLM-L12-v2',{revision:'d56d66f3a4258284c268d113e0202d7ec9078f6c',device:'wasm',dtype:'q8',progress_callback:p=>self.postMessage({type:'progress',message:p.status==='progress'?`下载 ${p.file} · ${Math.round(p.progress)}%`:'正在准备语义模型…'})});
  const options={pooling:'mean',normalize:true};
  for(const text of [data.query,...data.candidates.map(c=>c.text)]){
   if(embed.tokenizer(text,{truncation:false}).input_ids.data.length>128)throw Error('文本超过语义模型的 128 token 范围，请缩短偏好或候选描述。');
  }
  const query=await embed(data.query,options),scores=[];
  for(let i=0;i<data.candidates.length;i++){
   self.postMessage({type:'progress',message:`理解候选 ${i+1}/${data.candidates.length}…`});
   const vector=await embed(data.candidates[i].text,options);
   let score=0;for(let j=0;j<query.data.length;j++)score+=query.data[j]*vector.data[j];
   scores.push({id:data.candidates[i].id,score});
  }
  self.postMessage({type:'result',scores});await embed.dispose();
 }catch(error){self.postMessage({type:'error',message:error.message});}
};
