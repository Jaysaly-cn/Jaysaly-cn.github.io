function initialize(){
 const projects=JSON.parse(document.querySelector('#project-catalogue').textContent);
 const dialog=document.querySelector('#archive');
 for(const button of document.querySelectorAll('[data-detail]')){
  button.addEventListener('click',()=>{
   const p=projects.find(p=>p.id===button.dataset.detail);
   if(!p)return;
   for(const [id,key] of [['title','name'],['reason','reason'],['engineering','engineering'],['model','model'],['tests','tests']])document.querySelector('#archive-'+id).textContent=p[key];
   document.querySelector('#archive-case').href='../cases/'+p.id+'.html';
   document.querySelector('#archive-source').href='https://github.com/Jaysaly-cn/Jaysaly-cn.github.io/tree/main/projects/'+p.id;
   dialog.setAttribute('aria-labelledby','archive-title');dialog.showModal();
  });
 }
 for(const button of document.querySelectorAll('[data-filter]')){
  button.addEventListener('click',()=>{
   let count=0;
   for(const item of document.querySelectorAll('[data-room]')){item.hidden=button.dataset.filter!=='all'&&item.dataset.room!==button.dataset.filter;if(!item.hidden)count++;}
   for(const b of document.querySelectorAll('[data-filter]'))b.setAttribute('aria-pressed',String(b===button));
   document.querySelector('#filter-status').textContent='显示 '+count+' 件作品';
  });
 }
 document.body.classList.add('enhanced');
}
try{initialize();}catch{/* The static cases, source links and details remain usable. */}
