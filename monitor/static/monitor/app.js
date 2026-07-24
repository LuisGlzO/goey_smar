(()=>{
  const root=document.documentElement;
  const themeButton=document.querySelector('[data-theme-toggle]');
  const savedTheme=localStorage.getItem('goey-theme')||'system';
  const systemTheme=()=>matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  const applyTheme=value=>{
    root.dataset.theme=value==='system'?systemTheme():value;
    root.dataset.themePreference=value;
    if(themeButton){
      themeButton.setAttribute('aria-label',`Tema: ${value}. Cambiar tema`);
      themeButton.title=`Tema: ${value}`;
      themeButton.querySelector('span').textContent=value==='dark'?'☾':value==='light'?'☀':'◐';
    }
  };
  applyTheme(savedTheme);
  themeButton?.addEventListener('click',()=>{
    const current=root.dataset.themePreference;
    const next=current==='system'?'light':current==='light'?'dark':'system';
    localStorage.setItem('goey-theme',next);
    applyTheme(next);
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{
    if(root.dataset.themePreference==='system')applyTheme('system');
  });

  const sidebar=document.querySelector('[data-sidebar]');
  const sidebarOpen=document.querySelector('[data-sidebar-open]');
  const sidebarClosers=document.querySelectorAll('[data-sidebar-close]');
  if(sidebar&&sidebarOpen){
    const mobileSidebar=matchMedia('(max-width: 950px)');
    const setSidebar=open=>{
      const shouldOpen=open&&mobileSidebar.matches;
      document.body.classList.toggle('sidebar-is-open',shouldOpen);
      sidebarOpen.setAttribute('aria-expanded',String(shouldOpen));
      sidebar.setAttribute('aria-hidden',String(mobileSidebar.matches&&!shouldOpen));
      if(shouldOpen)sidebar.querySelector('a,button')?.focus();
      else if(open===false&&mobileSidebar.matches)sidebarOpen.focus();
    };
    sidebarOpen.addEventListener('click',()=>setSidebar(true));
    sidebarClosers.forEach(element=>element.addEventListener('click',()=>setSidebar(false)));
    sidebar.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>{
      if(mobileSidebar.matches)setSidebar(false);
    }));
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&document.body.classList.contains('sidebar-is-open'))setSidebar(false);
    });
    mobileSidebar.addEventListener('change',event=>{
      document.body.classList.remove('sidebar-is-open');
      sidebarOpen.setAttribute('aria-expanded','false');
      sidebar.setAttribute('aria-hidden',String(event.matches));
    });
    sidebar.setAttribute('aria-hidden',String(mobileSidebar.matches));
  }

  const alertDialog=document.querySelector('#alert-dialog');
  if(alertDialog){
    document.querySelectorAll('[data-product-card]').forEach(card=>card.addEventListener('click',()=>{
      alertDialog.querySelector('[data-modal-name]').textContent=card.dataset.name;
      alertDialog.querySelector('[data-modal-asin]').textContent=card.dataset.asin;
      alertDialog.querySelector('[data-modal-status]').textContent=card.dataset.status;
      alertDialog.querySelector('form').action=card.dataset.action;
      alertDialog.showModal();
    }));
    alertDialog.querySelectorAll('[data-modal-close]').forEach(el=>el.addEventListener('click',()=>alertDialog.close()));
    alertDialog.addEventListener('click',event=>{if(event.target===alertDialog)alertDialog.close();});
  }

  const bulkDialog=document.querySelector('#bulk-dialog');
  if(bulkDialog){
    const checkboxes=[...document.querySelectorAll('[data-product-select]')];
    const selectPage=document.querySelector('[data-select-page]');
    const openBulk=document.querySelector('[data-open-bulk]');
    const countLabel=document.querySelector('[data-selection-count]');
    const selected=()=>checkboxes.filter(item=>item.checked);
    const syncSelection=()=>{
      const count=selected().length;
      countLabel.textContent=count;
      openBulk.disabled=count===0;
      selectPage.checked=count===checkboxes.length&&checkboxes.length>0;
      selectPage.indeterminate=count>0&&count<checkboxes.length;
    };
    selectPage?.addEventListener('change',()=>{checkboxes.forEach(item=>item.checked=selectPage.checked);syncSelection();});
    checkboxes.forEach(item=>item.addEventListener('change',syncSelection));
    openBulk?.addEventListener('click',()=>{
      const values=selected().map(item=>item.value);
      bulkDialog.querySelector('[data-bulk-ids]').value=values.join(',');
      bulkDialog.querySelector('[data-bulk-count]').textContent=values.length;
      bulkDialog.showModal();
    });
    bulkDialog.querySelectorAll('[data-bulk-close]').forEach(el=>el.addEventListener('click',()=>bulkDialog.close()));
    bulkDialog.addEventListener('click',event=>{if(event.target===bulkDialog)bulkDialog.close();});
    syncSelection();
  }
})();
