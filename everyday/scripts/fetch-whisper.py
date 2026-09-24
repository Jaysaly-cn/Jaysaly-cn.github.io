"""Fetch a pinned ModelScope ONNX snapshot, verifying the hub's SHA-256 per file."""
import urllib.request,json,hashlib,concurrent.futures
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'vendor/models/onnx-community/whisper-tiny'
host='https://modelscope.cn'
model='onnx-community/whisper-tiny'
wanted={'config.json','generation_config.json','preprocessor_config.json','tokenizer_config.json','tokenizer.json','README.md','onnx/encoder_model_quantized.onnx','onnx/decoder_model_merged_quantized.onnx'}
manifest=root/'manifest.json'
if manifest.exists(): files=json.loads(manifest.read_text())['files']
else:
 listing=json.load(urllib.request.urlopen(f'{host}/api/v1/models/{model}/repo/files?Revision=master&Recursive=true',timeout=30))
 files=[{'path':x['Path'],'revision':x['Revision'],'sha256':x['Sha256'],'bytes':x['Size']} for x in listing['Data']['Files'] if x['Path'] in wanted]
 if {x['path'] for x in files}!=wanted: raise RuntimeError('Incomplete model snapshot')
 root.mkdir(parents=True,exist_ok=True);manifest.write_text(json.dumps({'source':host+'/models/'+model,'files':files},indent=2),encoding='utf-8')
def fetch(f):
 target=root/f['path'];target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==f['sha256']:return
 url=f"{host}/models/{model}/resolve/{f['revision']}/{f['path']}"
 data=urllib.request.urlopen(url,timeout=90).read()
 if len(data)!=f['bytes'] or hashlib.sha256(data).hexdigest()!=f['sha256']:raise RuntimeError('Model integrity mismatch: '+f['path'])
 target.write_bytes(data);print(f['path'],len(data),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,files))
