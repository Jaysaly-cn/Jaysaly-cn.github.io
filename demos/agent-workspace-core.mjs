export const initial=()=>({release:false,instance:null,revision:0,goal:'',files:[],accepted:false,events:[]});
const require=(ok,message)=>{if(!ok)throw Error(message);};
export function transition(input,action,data={}){
 const s=structuredClone(input),i=s.instance;let message;
 switch(action){
 case 'publish':require(!s.release,'Release 已发布。');s.release=true;message='发布演示员工包 1.0.0，固定版本。';break;
 case 'deploy':require(s.release,'请先发布 Release。');require(!i||i.retired,'现有实例仍在使用，请先退役。');require(['Codex','Claude Code','DeepSeek'].includes(data.executor),'请选择有效执行器。');s.instance={executor:data.executor,credentials:false,ack:false,evaluated:false,active:false,retired:false};message='创建 '+data.executor+' 实例，等待配置与设备确认。';break;
 case 'credentials':case 'ack':require(i&&!i.retired,'请先部署可用实例。');i[action]=true;message=action==='ack'?'收到模拟设备 ACK。':'演示配置状态已备齐（没有保存凭据）。';break;
 case 'evaluate':require(i&&!i.retired&&i.credentials&&i.ack,'配置与设备 ACK 都完成后才能测评。');i.evaluated=true;message='规则测评通过：版本、配置与 ACK 已备齐；非模型质量测评。';break;
 case 'activate':require(i&&!i.retired&&i.evaluated,'请先完成规则测评。');i.active=true;message='实例激活，可供协作演示使用。';break;
 case 'retire':require(i&&!i.retired,'没有可退役实例。');i.active=false;i.retired=true;message='实例退役，保留历史交付记录。';break;
 case 'goal':require(i?.active,'请先在 HeliX 激活实例。');require(data.text?.trim()&&data.text.length<=800,'请填写 1–800 字的目标。');s.goal=data.text.trim();s.revision++;s.accepted=false;message=`负责人公开要求 v${s.revision}，产品与研发接手；旧稿及复核保留。`;break;
 case 'draft':require(i?.active&&s.revision,'先激活实例并公开目标。');require(['产品','研发'].includes(data.author),'未知作者。');require(!s.files.some(f=>f.revision===s.revision&&f.author===data.author),'当前作者已交稿，请修订现有原件。');s.files.push({id:s.files.length+1,author:data.author,revision:s.revision,version:1,text:`# ${data.author==='产品'?'需求草稿':'研发核查清单'}\n\n当前目标：${s.goal}\n\n${data.author==='产品'?'使用者：夜间阅读者（待核实）\n待确认：亮度、眩光、预算口径及验收标准。':'待核对：预算是否含配件、供电与散热、样机验证方式。'}\n\n确定性演示模板，非模型生成；请编辑后复核。`,reviews:[],history:[]});s.accepted=false;message=data.author+'提交原件，等待非作者核对。';break;
 case 'edit':case 'review':{
 const f=s.files.find(f=>f.id===data.id);require(f&&f.revision===s.revision,'只能处理当前要求对应的原件。');
 if(action==='edit'){require(data.text?.trim()&&data.text.length<=5000,'原件需为 1–5000 字。');require(data.text!==f.text,'内容未改变。');f.history.push({version:f.version,text:f.text,reviews:structuredClone(f.reviews)});f.text=data.text;f.version++;f.reviews=[];message=`${f.author}修订至 v${f.version}，旧复核失效并保留。`;}
 else{require(['产品','研发','市场'].includes(data.reviewer)&&data.reviewer!==f.author,'复核者必须是非作者。');require(data.evidence?.trim()&&data.evidence.length<=800,'请填写实际读取与核对依据（最多 800 字）。');f.reviews.push({reviewer:data.reviewer,evidence:data.evidence.trim(),version:f.version});message=`${data.reviewer}核对${f.author}原件 v${f.version}，保留依据。`;}
 s.accepted=false;break;}
 case 'accept':require(ready(s),'当前两份原件都需非作者复核，且实例可用。');require(data.evidence?.trim()&&data.evidence.length<=800,'请填写人工核查依据（最多 800 字）。');require(!s.accepted,'当前交付已接受。');s.accepted=true;message='人工接受当前交付：'+data.evidence.trim();break;
 case 'return':require(s.revision,'尚未公开目标。');require(data.evidence?.trim()&&data.evidence.length<=800,'请填写退回依据（最多 800 字）。');s.revision++;s.accepted=false;message='退回原作者，当前要求升为 v'+s.revision+'：'+data.evidence.trim();break;
 default:throw Error('未知动作。');
 }
 s.events.push({sequence:s.events.length+1,revision:s.revision,message});return s;
}
export function ready(s){const files=s.files.filter(f=>f.revision===s.revision);return !!s.instance?.active&&files.length===2&&files.every(f=>f.reviews.some(r=>r.reviewer!==f.author&&r.version===f.version));}
