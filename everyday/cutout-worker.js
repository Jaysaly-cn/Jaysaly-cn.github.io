import { removeBackground } from '@imgly/background-removal';
self.onmessage = async ({data}) => {
  try {
    const resources=new Map();
    const blob = await removeBackground(data.image, {
      model: 'isnet_quint8', device: 'cpu',
      progress: (key,current,total) => { if(key.startsWith('fetch:'))resources.set(key,total);self.postMessage({type:'progress',key,current,total}); }
    });
    self.postMessage({type:'result',blob,resourceBytes:[...resources.values()].reduce((a,b)=>a+b,0)});
  } catch(error) { self.postMessage({type:'error',message:error.message}); }
};
