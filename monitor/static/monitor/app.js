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

  const confirmationDialog=document.querySelector('[data-confirm-dialog]');
  if(confirmationDialog){
    let pendingConfirmation=null;
    let pendingSubmitter=null;
    document.querySelectorAll('form[data-confirm]').forEach(form=>form.addEventListener('submit',event=>{
      if(form.dataset.confirmApproved==='true'){
        delete form.dataset.confirmApproved;
        return;
      }
      event.preventDefault();
      pendingConfirmation=form;
      pendingSubmitter=event.submitter;
      confirmationDialog.querySelector('[data-confirm-title]').textContent=form.dataset.confirmTitle||'Confirmar acción';
      confirmationDialog.querySelector('[data-confirm-message]').textContent=form.dataset.confirmMessage||'Esta acción no se puede deshacer.';
      confirmationDialog.querySelector('[data-confirm-submit]').textContent=form.dataset.confirmLabel||'Confirmar';
      confirmationDialog.showModal();
    }));
    confirmationDialog.querySelectorAll('[data-confirm-cancel]').forEach(button=>button.addEventListener('click',()=>{
      confirmationDialog.close();
    }));
    confirmationDialog.querySelector('[data-confirm-submit]').addEventListener('click',()=>{
      if(!pendingConfirmation)return;
      const form=pendingConfirmation;
      const submitter=pendingSubmitter;
      form.dataset.confirmApproved='true';
      confirmationDialog.close();
      submitter?form.requestSubmit(submitter):form.requestSubmit();
    });
    confirmationDialog.addEventListener('click',event=>{
      if(event.target===confirmationDialog)confirmationDialog.close();
    });
    confirmationDialog.addEventListener('close',()=>{
      pendingConfirmation=null;
      pendingSubmitter=null;
    });
  }

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

  const asinInput=document.querySelector('[data-asin-input]');
  const asinChips=document.querySelector('[data-asin-chips]');
  if(asinInput&&asinChips){
    const renderAsinChips=()=>{
      const values=[...new Set(asinInput.value.toUpperCase().split(/[\s,;]+/).filter(Boolean))];
      asinChips.replaceChildren(...values.slice(0,50).map(value=>{
        const chip=document.createElement('span');
        chip.className=/^[A-Z0-9]{10}$/.test(value)?'asin-chip':'asin-chip invalid';
        chip.textContent=value;
        return chip;
      }));
    };
    asinInput.addEventListener('input',renderAsinChips);
    renderAsinChips();
  }

  const copyFeedback=document.querySelector('[data-copy-feedback]');
  const copyText=async text=>{
    if(navigator.clipboard?.writeText){
      await navigator.clipboard.writeText(text);
      return;
    }
    const temporary=document.createElement('textarea');
    temporary.value=text;
    temporary.style.position='fixed';
    temporary.style.opacity='0';
    document.body.appendChild(temporary);
    temporary.select();
    document.execCommand('copy');
    temporary.remove();
  };
  document.querySelectorAll('[data-copy-url]').forEach(button=>button.addEventListener('click',async()=>{
    try{
      await copyText(button.dataset.url);
      button.textContent='Copiado ✓';
      copyFeedback.textContent='Enlace copiado al portapapeles.';
      setTimeout(()=>{button.textContent='Copiar';},1800);
    }catch{
      copyFeedback.textContent='No se pudo copiar automáticamente. Selecciona el enlace y cópialo manualmente.';
    }
  }));
  document.querySelector('[data-copy-all]')?.addEventListener('click',async event=>{
    const urls=[...document.querySelectorAll('[data-generated-url]')].map(input=>input.value).filter(Boolean);
    try{
      await copyText(urls.join('\n'));
      event.currentTarget.textContent='Copiados ✓';
      copyFeedback.textContent=`${urls.length} enlace${urls.length===1?'':'s'} copiado${urls.length===1?'':'s'} al portapapeles.`;
      setTimeout(()=>{event.currentTarget.textContent='Copiar todos';},1800);
    }catch{
      copyFeedback.textContent='No se pudieron copiar automáticamente. Copia los enlaces individualmente.';
    }
  });

  const alertDialog=document.querySelector('#alert-dialog');
  if(alertDialog){
    document.querySelectorAll('[data-product-card]').forEach(card=>card.addEventListener('click',()=>{
      alertDialog.querySelector('[data-modal-name]').textContent=card.dataset.name;
      alertDialog.querySelector('[data-modal-asin]').textContent=card.dataset.asin;
      alertDialog.querySelector('[data-modal-status]').textContent=card.dataset.status;
      alertDialog.querySelector('[data-modal-observations]').textContent=card.dataset.observations||'';
      alertDialog.querySelector('form').action=card.dataset.action;
      alertDialog.showModal();
    }));
    alertDialog.querySelectorAll('[data-modal-close]').forEach(el=>el.addEventListener('click',()=>alertDialog.close()));
    alertDialog.addEventListener('click',event=>{if(event.target===alertDialog)alertDialog.close();});
  }

  const assignmentRoot=document.querySelector('[data-group-assignment]');
  if(assignmentRoot){
    const lists={
      available:assignmentRoot.querySelector('[data-assignment-list="available"]'),
      assigned:assignmentRoot.querySelector('[data-assignment-list="assigned"]'),
    };
    const searches={
      available:assignmentRoot.querySelector('[data-assignment-search="available"]'),
      assigned:assignmentRoot.querySelector('[data-assignment-search="assigned"]'),
    };
    const moveButtons={
      assigned:assignmentRoot.querySelector('[data-assignment-move="assigned"]'),
      available:assignmentRoot.querySelector('[data-assignment-move="available"]'),
    };
    const items=side=>[...lists[side].querySelectorAll('[data-assignment-item]')];
    const normalize=value=>value.toLocaleLowerCase('es').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
    const applyFilter=side=>{
      const query=normalize(searches[side].value.trim());
      items(side).forEach(item=>{item.hidden=query&&!normalize(item.dataset.search).includes(query);});
    };
    const syncHidden=()=>{
      const hidden=assignmentRoot.querySelector('[data-assignment-hidden]');
      hidden.replaceChildren(...items('assigned').map(item=>{
        const input=document.createElement('input');
        input.type='hidden';
        input.name='products';
        input.value=item.dataset.productId;
        return input;
      }));
    };
    const sync=()=>{
      ['available','assigned'].forEach(side=>{
        applyFilter(side);
        const sideItems=items(side);
        const visible=sideItems.filter(item=>!item.hidden).length;
        assignmentRoot.querySelector(`[data-${side}-total]`).textContent=sideItems.length;
        assignmentRoot.querySelector(`[data-${side}-badge]`).textContent=sideItems.length;
        assignmentRoot.querySelector(`[data-${side}-visible]`).textContent=visible;
        lists[side].querySelector('[data-assignment-empty]').hidden=visible>0;
      });
      moveButtons.assigned.disabled=!items('available').some(item=>item.querySelector('[data-assignment-select]').checked);
      moveButtons.available.disabled=!items('assigned').some(item=>item.querySelector('[data-assignment-select]').checked);
      syncHidden();
    };
    assignmentRoot.querySelectorAll('[data-assignment-select]').forEach(input=>input.addEventListener('change',sync));
    Object.entries(searches).forEach(([side,input])=>input.addEventListener('input',()=>{applyFilter(side);sync();}));
    Object.entries(moveButtons).forEach(([target,button])=>button.addEventListener('click',()=>{
      const source=target==='assigned'?'available':'assigned';
      const empty=lists[target].querySelector('[data-assignment-empty]');
      items(source).filter(item=>item.querySelector('[data-assignment-select]').checked).forEach(item=>{
        item.querySelector('[data-assignment-select]').checked=false;
        lists[target].insertBefore(item,empty);
        item.draggable=target==='assigned';
        item.toggleAttribute('data-sort-item',target==='assigned');
        let controls=item.querySelector('.sort-controls');
        if(target==='assigned'&&!controls){
          controls=document.createElement('span'); controls.className='sort-controls';
          controls.innerHTML='<button type="button" class="secondary" data-sort-move="up">↑</button><button type="button" class="secondary" data-sort-move="down">↓</button>';
          item.append(controls);
        }else if(target==='available'){controls?.remove();}
      });
      sync();
    }));
    assignmentRoot.addEventListener('submit',syncHidden);
    sync();
  }

  const initSortable=(list,onChange=()=>{})=>{
    if(!list)return;
    let dragged=null;
    list.addEventListener('dragstart',event=>{dragged=event.target.closest('[data-sort-item]');dragged?.classList.add('sorting');});
    list.addEventListener('dragover',event=>{if(!dragged)return;event.preventDefault();const target=event.target.closest('[data-sort-item]');if(!target||target===dragged)return;const box=target.getBoundingClientRect();list.insertBefore(dragged,event.clientY<box.top+box.height/2?target:target.nextSibling);onChange();});
    list.addEventListener('dragend',()=>{dragged?.classList.remove('sorting');dragged=null;onChange();});
    list.addEventListener('click',event=>{const button=event.target.closest('[data-sort-move]');if(!button)return;const item=button.closest('[data-sort-item]');if(button.dataset.sortMove==='up'&&item.previousElementSibling?.matches('[data-sort-item]'))list.insertBefore(item,item.previousElementSibling);if(button.dataset.sortMove==='down'&&item.nextElementSibling?.matches('[data-sort-item]'))list.insertBefore(item.nextElementSibling,item);onChange();});
  };
  if(assignmentRoot)initSortable(assignmentRoot.querySelector('[data-assignment-list="assigned"]'),()=>assignmentRoot.querySelector('[data-assignment-hidden]')?.replaceChildren(...[...assignmentRoot.querySelectorAll('[data-assignment-list="assigned"] [data-assignment-item]')].map(item=>{const input=document.createElement('input');input.type='hidden';input.name='products';input.value=item.dataset.productId;return input;})));
  document.querySelectorAll('[data-sort-form]').forEach(form=>{const list=form.querySelector('[data-sort-list]');const syncOrder=()=>{const hidden=form.querySelector('[data-sort-hidden]');hidden.replaceChildren(...[...list.querySelectorAll('[data-sort-item]')].map(item=>{const input=document.createElement('input');input.type='hidden';input.name='groups';input.value=item.dataset.sortId;return input;}));};initSortable(list,syncOrder);form.addEventListener('submit',syncOrder);syncOrder();});

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
