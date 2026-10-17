'use strict';

function clearCommunity() {
  state.libraries = [];
  state.reading = [];
  $('admin-reset-code').value='';
  $('recovery-finish').reset();
  $('admin-libraries').replaceChildren();
  ['suggestions','friend-requests','shared-libraries','reading-stats','reading-journal','popular-books','admin-stats','admin-users','admin-books','admin-events'].forEach(id => $(id).replaceChildren());
  $('settings-form').reset();
  $('email-code').value = '';
  $('admin-open').hidden = true;
}

function applySettings() {
  const p = state.me;
  $('username').textContent = p.display_name || p.username;
  $('setting-name').value = p.first_name || '';
  $('setting-lastname').value = p.last_name || '';
  $('setting-town').value = p.town || '';
  $('setting-discovery').checked = p.discoverable;
  $('setting-private').checked = p.private_library;
  $('setting-secondary').checked = p.secondary_review;
  $('scan-mode').value = p.review_mode || 'cleanup';
  $('scan-mode').disabled = !p.secondary_review;
  $('setting-email').value = p.email || '';
  $('setting-email-notify').checked = p.email_notifications;
  $('email-status').textContent = !p.email_available ? 'Email delivery is not configured on this server yet.' : p.email_verified ? 'Email verified. Notifications follow your preference above.' : 'Save your email, then verify it to receive notifications.';
  $('email-send').disabled = !p.email_available;
  $('email-verify').disabled = !p.email_available;
  $('admin-open').hidden = !p.is_admin;
  document.querySelectorAll('.navigation [data-tab="friends"], .navigation [data-tab="trades"]').forEach(b => b.hidden = p.private_library);
  $('review-available').closest('label').hidden = p.private_library;
}

function fillLibraries(id, libraries) {
  const selected = $(id).value;
  $(id).replaceChildren(new Option('My library', ''));
  libraries.forEach(l => $(id).add(new Option(l.name, l.id)));
  $(id).value = libraries.some(l => l.id === selected) ? selected : '';
}

async function refreshCommunity() {
  const epoch = state.epoch, tab = state.tab;
  const libraries = await api('/libraries');
  if (epoch !== state.epoch) return;
  state.libraries = libraries;
  fillLibraries('scan-library',libraries);
  fillLibraries('queue-library',libraries);
  if (tab !== state.tab) return;
  if (tab === 'friends') {
    const [suggestions, requests] = await Promise.all([api('/people/suggestions'),api('/people/requests')]);
    if (epoch !== state.epoch || tab !== state.tab) return;
    renderSuggestions(suggestions,requests);
  }
  if (tab === 'settings') renderSharedLibraries();
  if (tab === 'stats') {
    const [stats, reading, popular] = await Promise.all([api('/me/stats'),api('/reading'),api('/popular')]);
    if (epoch !== state.epoch || tab !== state.tab) return;
    state.reading = reading;
    renderStats($('reading-stats'),stats, {books:'Books on your shelf',unique_books:'Unique books',reviews:'Written reviews',pages_read:'Pages read',finished:'Books finished',books_traded:'Books given',books_received:'Books received'});
    $('reading-journal').replaceChildren();
    if (!reading.length) $('reading-journal').append(e('p','muted','Your reading journal is empty.'));
    reading.forEach(r => {
      const row = e('article','panel compact-row');
      row.append(e('span','',r.title + ' · ' + r.pages_read + ' pages'),button('Update log','secondary',() => openReading(r)));
      $('reading-journal').append(row);
    });
    $('popular-books').replaceChildren();
    popular.forEach(b => $('popular-books').append(e('p','',b.title+' — '+b.author+' · '+b.owners+' shelves')));
    if (!popular.length) $('popular-books').append(e('p','muted','Community favorites will appear as more readers opt into discovery.'));
  }
  if (tab === 'admin' && state.me.is_admin) {
    const [stats,events,libraries] = await Promise.all([api('/admin/stats'),api('/admin/events'),api('/admin/libraries')]);
    if (epoch !== state.epoch || tab !== state.tab) return;
    renderSharedLibraries(libraries,$('admin-libraries'));
    renderStats($('admin-stats'),stats,{users:'Accounts',banned:'Banned accounts',books:'Active books',queued_scans:'Pending scans',completed_trades:'Completed swaps',abuse_flags_24h:'Signals in 24 hours',email_failures:'Failed emails',database_mb:'Database MB'});
    $('admin-events').replaceChildren();
    [...events.abuse,...events.actions].sort((a,b)=>b.created-a.created).slice(0,50).forEach(event => $('admin-events').append(e('p','small',new Date(event.created*1000).toLocaleString()+' · '+(event.reason || event.action)+' · '+(event.actor || event.target))));
    if (!events.abuse.length && !events.actions.length) $('admin-events').append(e('p','muted','No recent activity.'));
  }
}

function renderStats(root, values, labels) {
  root.replaceChildren();
  for (const [key,label] of Object.entries(labels)) {
    const card = e('div','panel stat-card');
    card.append(e('strong','',String(values[key] ?? 0)),e('span','muted',label));
    root.append(card);
  }
}

function renderSuggestions(people, requests) {
  $('suggestions').replaceChildren();
  if (!people.length) $('suggestions').append(e('p','muted',state.me.discoverable ? 'No matches yet. Add a town in Settings or connect with friends using invite codes.' : 'Discovery is off. You can still use private invite codes.'));
  for (const person of people) {
    const row = e('article','compact-row');
    const info = e('div');
    info.append(e('strong','',person.display_name || person.username),e('p','small muted','@'+person.username+' · '+[person.same_town?'Same town':'',person.mutual_friends?person.mutual_friends+' mutual friends':''].filter(Boolean).join(' · ')));
    row.append(info,button('Add friend','secondary',async () => {
      await api('/people/'+person.id+'/request',{method:'POST'});
      await refreshCommunity();
      toast('Friend request sent.');
    }));
    $('suggestions').append(row);
  }
  $('friend-requests').replaceChildren();
  if (!requests.length) $('friend-requests').append(e('p','muted','No pending requests.'));
  for (const request of requests) {
    const incoming = request.recipient === state.me.id;
    const other = incoming ? request.sender : request.recipient;
    const row = e('article','compact-row');
    row.append(e('span','',(request.display_name || request.username)+(incoming?' wants to connect':' · request sent')));
    if (incoming) row.append(button('Accept','primary',async () => {
      await api('/people/'+other+'/accept',{method:'POST'}); await refreshAll();
    }));
    row.append(button(incoming?'Decline':'Cancel','text-button',async () => {
      await api('/people/'+other+'/request',{method:'DELETE'}); await refreshCommunity();
    }));
    $('friend-requests').append(row);
  }
}

function renderSharedLibraries(libraries = state.libraries, root = $('shared-libraries')) {
  root.replaceChildren();
  if (!libraries.length) root.append(e('p','muted','No shared libraries yet. Ask a library manager to add your username.'));
  for (const library of libraries) {
    const card = e('details','library-settings');
    const heading=e('summary','library-card-summary');
    heading.append(e('span','library-name',library.name),e('span','library-visibility',library.is_public?'Public':'Private'));
    card.append(heading,e('p','small muted',library.books+' saved books'));
    if (state.libraries.some(memberLibrary=>memberLibrary.id===library.id)) {
    card.append(button('Export CSV','secondary',()=>exportLibrary(library)));
    card.append(button('Browse catalog','secondary',() => openLibrary('lib:'+library.id)));
    card.append(button('Scan into library','secondary',() => {$('scan-library').value=library.id; navigate('scan');}));
    card.append(button('Open shared queue','secondary',() => {$('queue-library').value=library.id; navigate('queue');}));
    }
    if (library.owner === state.me.id || state.me.is_admin) {
      const visibilityLabel=e('label','check');
      const visibility=e('input');visibility.type='checkbox';visibility.setAttribute('role','switch');visibility.checked=Boolean(library.is_public);
      visibilityLabel.append(visibility,document.createTextNode('Public library'));
      card.append(visibilityLabel,e('p','small muted','Public means anyone can browse the catalog and book photos without signing in.'));
      visibility.addEventListener('change',async()=>{
        const previous=Boolean(library.is_public);
        if(visibility.checked && !confirm('Make this library’s saved books, shelf locations, and photos visible to everyone?')){visibility.checked=previous;return;}
        visibility.disabled=true;
        try{await api('/libraries/'+library.id+'/visibility',{method:'PATCH',body:{is_public:visibility.checked}});library.is_public=visibility.checked;heading.querySelector('.library-visibility').textContent=visibility.checked?'Public':'Private';toast(visibility.checked?'Library is public.':'Library is private.');}
        catch(err){visibility.checked=previous;toast(err.message);}
        finally{visibility.disabled=false;}
      });
      const form = e('form','member-form');
      const label = e('label','','Give scanning permission to a username');
      const input = e('input'); input.required=true; input.pattern='[a-zA-Z0-9_]{3,32}'; input.placeholder='Existing username';
      label.append(input); const submit=e('button','primary','Add member'); submit.type='submit';
      form.append(label,submit);
      const memberList=e('div');
      const loadMembers=async()=>{
        const members=await api('/libraries/'+library.id+'/members');
        memberList.replaceChildren();
        members.forEach(member=>{
          const row=e('div','compact-row'); row.append(e('span','',member.display_name || member.username));
          if(member.id!==library.owner) row.append(button('Remove access','text-button danger',async()=>{
            if(!confirm('Remove '+member.username+' from '+library.name+'? They will lose access to its queue and catalog.')) return;
            await api('/libraries/'+library.id+'/members/'+member.id,{method:'DELETE'}); await loadMembers();
          }));
          else row.append(e('span','small muted','Manager'));
          memberList.append(row);
        });
      };
      form.addEventListener('submit',event=>{
        event.preventDefault(); formAction(form,async()=>{
          await api('/libraries/'+library.id+'/members',{method:'POST',body:{username:input.value.trim()}});
          input.value=''; await loadMembers(); toast('Member can now scan into this library.');
        });
      });
      card.addEventListener('toggle',()=>{if(card.open) loadMembers().catch(err=>toast(err.message));});
      card.append(form,memberList);
    }
    if (state.me.is_admin) card.append(button('Delete library','text-button danger',()=>openDeleteLibrary(library)));
    root.append(card);
  }
}

$('settings-form').addEventListener('submit',event=>{
  event.preventDefault();
  formAction(event.currentTarget,async()=>{
    if($('setting-private').checked && !state.me.private_library && !confirm('Hide your personal library and cancel all open swaps? Shared-library memberships are kept.')) return;
    state.me=await api('/me/profile-setup',{method:'POST',body:{first_name:$('setting-name').value,last_name:$('setting-lastname').value,town:$('setting-town').value}});
    state.me=await api('/me/settings',{method:'PATCH',body:{discoverable:$('setting-discovery').checked,private_library:$('setting-private').checked,secondary_review:$('setting-secondary').checked,review_mode:$('scan-mode').value,email:$('setting-email').value,email_notifications:$('setting-email-notify').checked}});
    applySettings(); state.owner=''; await refreshAll(); toast('Settings saved.');
  },'settings-error');
});
$('setting-secondary').addEventListener('change',()=>{$('scan-mode').disabled=!$('setting-secondary').checked;});
$('queue-library').addEventListener('change',renderQueue);
$('bulk-review').addEventListener('click',()=>formAction($('page-queue'),async()=>{
  const library=$('queue-library').value;
  const count=state.scans.filter(s=>s.status==='ready' && (s.library_id || '')===library).length;
  if(!count){toast('No finished scans to accept yet.');return;}
  if(!confirm('Save '+count+' ready books without checking each result? AI can misread titles, authors, and ISBNs. Incomplete results stay in the queue. Saved books are not offered for trade.')) return;
  const result=await api(library?'/libraries/'+library+'/accept-ready':'/queue/accept-ready',{method:'POST',body:{acknowledge:true}});
  await refreshAll(); toast(result.saved.length+' saved. '+result.skipped.length+' still need a manual review.');
}));
$('email-send').addEventListener('click',()=>formAction($('settings-form'),async()=>{
  if($('setting-email').value.trim()!==state.me.email) throw new Error('Save settings before requesting a verification code.');
  await api('/me/email/send-code',{method:'POST'}); toast('Verification email queued. Check your inbox.');
}));
$('email-verify').addEventListener('click',()=>formAction($('settings-form'),async()=>{
  await api('/me/email/verify',{method:'POST',body:{code:$('email-code').value.trim()}});
  state.me=await api('/me'); applySettings(); $('email-code').value=''; toast('Email verified.');
}));

async function openReading(book) {
  const logs=await api('/reading');
  state.reading=logs;
  const id=book.book_id || book.id;
  const row=logs.find(r=>r.book_id===id) || {pages_read:0,review:'',rating:'',finished:false};
  state.readingBook=id;
  $('reading-title').textContent=book.title;
  $('reading-pages').value=row.pages_read;
  $('reading-review').value=row.review;
  $('reading-rating').value=row.rating || '';
  $('reading-finished').checked=Boolean(row.finished);
  $('reading-error').textContent='';
  $('book-dialog').close();
  $('reading-dialog').showModal();
}
$('reading-open').addEventListener('click',()=>openReading(state.book).catch(err=>toast(err.message)));
$('reading-form').addEventListener('submit',event=>{
  event.preventDefault(); formAction(event.currentTarget,async()=>{
    await api('/reading/'+state.readingBook,{method:'PUT',body:{pages_read:Number($('reading-pages').value),review:$('reading-review').value,rating:$('reading-rating').value?Number($('reading-rating').value):null,finished:$('reading-finished').checked}});
    $('reading-dialog').close(); await refreshCommunity(); toast('Reading log saved.');
  },'reading-error');
});
$('create-library-form').addEventListener('submit',event=>{
  event.preventDefault(); formAction(event.currentTarget,async()=>{
    await api('/libraries',{method:'POST',body:{name:$('new-library-name').value,is_public:$('new-library-public').checked}});
    $('new-library-public').checked=false; $('new-library-name').value=''; navigate('settings'); toast('Library created. Open it below to add members.');
  });
});
$('admin-user-search').addEventListener('submit',event=>{
  event.preventDefault(); formAction(event.currentTarget,async()=>{
    const users=await api('/admin/users?q='+encodeURIComponent($('admin-user-query').value));
    $('admin-users').replaceChildren();
    if(!users.length) $('admin-users').append(e('p','muted','No accounts found.'));
    users.forEach(user=>{
      const row=e('div','compact-row');
      row.append(e('span','',user.username+(user.banned?' · banned':'')),button(user.banned?'Unban':'Ban','secondary',async()=>{
        if(!confirm((user.banned?'Restore access for ':'Ban ')+user.username+'?')) return;
        await api('/admin/users/'+user.id,{method:'PATCH',body:{banned:!user.banned}});
        $('admin-user-search').requestSubmit(); await refreshCommunity();
      }));
      if (!user.banned) row.append(button('Reset password','secondary',()=>requestAdminReset(user)));
      $('admin-users').append(row);
    });
  });
});
$('admin-book-search').addEventListener('submit',event=>{
  event.preventDefault(); formAction(event.currentTarget,async()=>{
    const books=await api('/admin/books?q='+encodeURIComponent($('admin-book-query').value));
    $('admin-books').replaceChildren();
    if(!books.length) $('admin-books').append(e('p','muted','No books found.'));
    books.forEach(book=>{
      const row=e('div','compact-row');row.append(e('span','',book.title+' · @'+book.username),button('Remove','text-button danger',async()=>{
        if(!confirm('Remove “'+book.title+'” and its photos? Open swaps for this book will be cancelled.'))return;
        await api('/admin/books/'+book.id,{method:'DELETE'}); row.remove();await refreshCommunity();
      }));$('admin-books').append(row);
    });
  });
});

async function exportLibrary(library) {
  const blob = await api('/libraries/'+encodeURIComponent(library.id)+'/export.csv',{responseType:'blob'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = (library.name.replace(/[^a-zA-Z0-9_-]+/g,'-').replace(/^-+|-+$/g,'') || 'shared-library')+'-books.csv';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
  toast('CSV ready. Check your browser downloads.');
}
$('library-export').addEventListener('click',()=>formAction($('library-export').parentElement,async()=>{
  const library=state.libraries.find(item=>'lib:'+item.id===state.owner);
  if(!library)throw new Error('Open a shared library first.');
  await exportLibrary(library);
}));
