'use strict';

function closeSections() {
  document.querySelectorAll('details[open]').forEach(d=>d.open=false);
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
}

function openLibrary(owner) {
  state.owner=owner;
  state.books=[];
  state.libraryLoading=true;
  $('library-search').value='';
  $('genre-filter').value='';
  $('available-only').checked=false;
  navigate('library');
}

function groupCopies(books) {
  const groups=new Map();
  for(const book of books) {
    const key=book.edition_key || JSON.stringify([book.isbn || '',book.title,book.author]);
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(book);
  }
  return [...groups.values()];
}

function openCopies(copies) {
  $('copies-title').textContent=copies[0].title;
  $('copies-count').textContent=copies.length+' copies';
  $('copies-author').textContent=copies[0].author;
  photoStrip($('copies-photos'),copies[0].images);
  $('copies-list').replaceChildren();
  copies.forEach((book,index)=>{
    const row=e('div','compact-row');
    row.append(e('span','','Copy '+(index+1)+(book.shelf ? ' · '+(book.shelf_label || book.shelf) : '')+' · '+(reserved(book.id)?'Reserved':book.available?'Available to trade':'On the shelf')),
      button('Open copy '+(index+1),'secondary',()=>{$('copies-dialog').close();openBook(book);}));
    $('copies-list').append(row);
  });
  $('copies-dialog').showModal();
}

function duplicateMessage(info) {
  const parts=[];
  if(info.saved_copies)parts.push(info.saved_copies+' saved '+(info.saved_copies===1?'copy':'copies'));
  if(info.ready_copies)parts.push(info.ready_copies+' other ready '+(info.ready_copies===1?'scan':'scans'));
  return 'Possible duplicate: '+parts.join(' and ')+'. '+(info.edition_known?'Matching ISBN.':'No ISBN; check the edition.')+' Saving adds another copy.';
}

function showProfileSetup() {
  const name=(state.me.display_name || '').trim().split(/\s+/);
  $('profile-first').value=state.me.first_name || name.shift() || '';
  $('profile-last').value=state.me.last_name || name.join(' ');
  $('profile-town').value=state.me.town || '';
  $('profile-error').textContent='';
  $('profile-dialog').showModal();
}
$('profile-dialog').addEventListener('cancel',event=>event.preventDefault());
$('profile-form').addEventListener('submit',event=>{
  event.preventDefault();formAction(event.currentTarget,async()=>{
    state.me=await api('/me/profile-setup',{method:'POST',body:{first_name:$('profile-first').value,last_name:$('profile-last').value,town:$('profile-town').value}});
    applySettings();$('profile-dialog').close();toast('Profile saved. Welcome to BookBridge.');
  },'profile-error');
});
$('profile-signout').addEventListener('click',()=>$('logout').click());

$('forgot-password').addEventListener('click',()=>{
  $('recovery-request').reset();$('recovery-finish').reset();
  $('recovery-username').value=$('auth-name').value;
  $('recovery-feedback').textContent='';$('recovery-error').textContent='';
  $('recovery-dialog').showModal();
});
$('recovery-request').addEventListener('submit',event=>{
  event.preventDefault();formAction(event.currentTarget,async()=>{
    const result=await api('/auth/forgot-password',{method:'POST',authenticated:false,body:{username:$('recovery-username').value.trim()}});
    $('recovery-feedback').textContent=result.message;
  },'recovery-feedback');
});
$('recovery-finish').addEventListener('submit',event=>{
  event.preventDefault();formAction(event.currentTarget,async()=>{
    if(!$('recovery-username').reportValidity())return;
    if($('recovery-password').value!==$('recovery-confirm').value)throw new Error('The passwords must match.');
    const result=await api('/auth/reset-password',{method:'POST',authenticated:false,body:{username:$('recovery-username').value.trim(),code:$('recovery-code').value.trim(),password:$('recovery-password').value}});
    $('recovery-dialog').close();$('recovery-finish').reset();
    if(state.register)$('auth-toggle').click();
    $('auth-name').value=$('recovery-username').value.trim();$('auth-password').value='';
    toast(result.message);
  },'recovery-error');
});
async function requestAdminReset(user) {
  if(!confirm('Generate a temporary password-reset code for '+user.username+'? Verify who is requesting access before sharing it.'))return;
  const result=await api('/admin/users/'+user.id+'/reset-code',{method:'POST'});
  $('admin-reset-code').value=result.code;
  $('reset-code-description').textContent='For @'+result.username+'. This code replaces any earlier reset code.';
  $('reset-code-dialog').showModal();
}
$('reset-code-dialog').addEventListener('close',()=>$('admin-reset-code').value='');
$('copy-reset-code').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText($('admin-reset-code').value);toast('Copied. Share privately.');}
  catch{$('admin-reset-code').select();$('admin-reset-code').setSelectionRange(0,$('admin-reset-code').value.length);toast('Touch and hold the selected code to copy it.');}
});
function openDeleteLibrary(library) {
  state.deletingLibrary=library;
  $('delete-library-description').textContent='You are deleting “'+library.name+'”.';
  $('delete-library-name').value='';$('delete-library-error').textContent='';
  $('delete-library-dialog').showModal();
}
$('delete-library-form').addEventListener('submit',event=>{
  event.preventDefault();formAction(event.currentTarget,async()=>{
    await api('/admin/libraries/'+state.deletingLibrary.id,{method:'DELETE',body:{confirm_name:$('delete-library-name').value}});
    $('delete-library-dialog').close();state.owner='';await refreshAll();toast('Library and its contents deleted.');
  },'delete-library-error');
});
closeSections();
if(state.token)startSession().catch(err=>{clearSession();$('auth-error').textContent=err.message;});

