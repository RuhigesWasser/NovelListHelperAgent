'use strict';
(() => {
  const tabs=[...document.querySelectorAll('[data-settings-tab]')];
  const content=document.querySelector('#settings-content'),picker=document.querySelector('#settings-picker');
  const positions=new Map();let active='';
  function selectSection(key,remember=true){
    if(!tabs.some(tab=>tab.dataset.settingsTab===key))key='llm';
    if(active)positions.set(active,content.scrollTop);
    active=key;
    for(const tab of tabs){
      const selected=tab.dataset.settingsTab===key;
      tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
      document.querySelector('#'+tab.getAttribute('aria-controls')).hidden=!selected;
    }
    picker.value=key;content.scrollTop=positions.get(key)||0;
    if(remember){try{sessionStorage.setItem('settings-section',key);}catch{}}
  }
  tabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>selectSection(tab.dataset.settingsTab));
    tab.addEventListener('keydown',event=>{
      let next=index;
      if(event.key==='ArrowDown')next=(index+1)%tabs.length;
      else if(event.key==='ArrowUp')next=(index+tabs.length-1)%tabs.length;
      else if(event.key==='Home')next=0;
      else if(event.key==='End')next=tabs.length-1;
      else return;
      event.preventDefault();tabs[next].focus();selectSection(tabs[next].dataset.settingsTab);
    });
  });
  picker.addEventListener('change',()=>selectSection(picker.value));
  let initial='llm';try{initial=sessionStorage.getItem('settings-section')||initial;}catch{}
  selectSection(initial,false);
})();
