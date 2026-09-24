export function splitReading(text){
 const value=text.trim();
 if(!value)throw Error('请先粘贴英文短文。');
 if(value.length>4000)throw Error('首版最多 4000 个字符，请分批阅读；不会截断原文。');
 if(!/[a-zA-Z]/.test(value))throw Error('当前仅支持英文到中文，请输入英文原文。');
 const sentences=[...new Intl.Segmenter('en',{granularity:'sentence'}).segment(value)].map(x=>x.segment.trim()).filter(Boolean);
 const parts=[];
 for(const sentence of sentences){
  // Long unpunctuated passages are split at spaces so the model never silently truncates input.
  let part='';
  for(const word of sentence.split(/\s+/)){
   if(word.length>450)throw Error('原文含过长的连续字符，请检查后重试。');
   if((part+' '+word).length>450){parts.push(part);part=word;}else part=part?part+' '+word:word;
  }
  if(part)parts.push(part);
 }
 if(parts.length>40)throw Error('首版最多 40 段，请减少短文长度。');
 return parts;
}
export function bilingualText(parts){return parts.map((p,i)=>`${i+1}. ${p.source}\n${p.translation||'（未完成翻译）'}`).join('\n\n');}
