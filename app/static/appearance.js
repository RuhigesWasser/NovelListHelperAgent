'use strict';
(() => {
  const root=document.documentElement,system=matchMedia('(prefers-color-scheme: dark)');
  let choice=['system','light','dark'].includes(root.dataset.theme)?root.dataset.theme:'system';
  function apply(){
    root.dataset.theme=choice;
    root.dataset.colorScheme=choice==='system'?(system.matches?'dark':'light'):choice;
    window.chrome?.webview?.postMessage({type:'appearance',theme:choice});
  }
  apply();system.addEventListener('change',apply);
  document.addEventListener('DOMContentLoaded',()=>{
    const control=document.querySelector('#appearance-theme');control.value=choice;
    control.addEventListener('change',async()=>{
      const previous=choice;choice=control.value;control.disabled=true;apply();
      try{await post('/api/appearance',{theme:choice});}
      catch(error){choice=previous;control.value=choice;apply();notice(error.message,true);}
      finally{control.disabled=false;}
    });
  });
})();
