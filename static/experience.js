'use strict';

// The server still owns scans, permissions and books. This file handles the
// first-use guide, photo viewer and the saved-book editing session.
const bookFields = ['book-title','book-author','book-isbn','book-shelf','book-available','book-genre'];
let bookEditor = null;

function beginBookDetails(book, allowed) {
  if (bookEditor) clearTimeout(bookEditor.timer);
  bookEditor = {id:book.id, epoch:state.epoch, allowed, editing:false,
    saved:JSON.stringify(reviewedBody('book')), timer:null, pending:null};
  setBookEditing(false);
}
function setBookEditing(editing) {
  if (!bookEditor) return;
  bookEditor.editing = editing && bookEditor.allowed;
  $('book-dialog').classList.toggle('editing',bookEditor.editing);
  bookFields.forEach(id => {
    if ($(id).type === 'checkbox' || $(id).tagName === 'SELECT') $(id).disabled = !bookEditor.editing;
    else $(id).readOnly = !bookEditor.editing;
  });
  $('edit-book').hidden = !bookEditor.allowed || bookEditor.editing;
  $('book-own-actions').hidden = !bookEditor.editing;
  $('retry-book-save').hidden = true;
  $('book-save-status').textContent = bookEditor.editing ? 'Changes save automatically' : 'Read-only';
}
function currentBookEditor(editor) {
  return bookEditor === editor && state.epoch === editor.epoch && state.me;
}
function validBookEdit() {
  if (!$('book-title').value.trim() || !$('book-author').value.trim()) {
    $('book-save-status').textContent = 'Add a title and author to save.';
    return false;
  }
  return $('book-form').checkValidity();
}
async function flushBookEdit() {
  const editor = bookEditor;
  if (!editor?.editing || !currentBookEditor(editor)) return;
  clearTimeout(editor.timer);
  if (editor.pending) { await editor.pending; return flushBookEdit(); }
  if (!validBookEdit()) throw new Error('Add a valid title and author before closing.');
  const body = reviewedBody('book'), snapshot = JSON.stringify(body);
  if (snapshot === editor.saved) return;
  $('book-save-status').textContent = 'Saving…';
  $('retry-book-save').hidden = true;
  editor.pending = (async () => {
    try {
      await api('/books/'+encodeURIComponent(editor.id),{method:'PATCH',body});
      if (!currentBookEditor(editor)) return;
      editor.saved = snapshot;
      for (const list of [state.books,state.ownBooks]) {
        const book = list.find(b=>b.id===editor.id);
        if (book) Object.assign(book,body);
      }
      Object.assign(state.book,body);
      $('book-error').textContent = '';
      $('book-save-status').textContent = 'All changes saved';
      if (state.tab==='library') renderLibrary();
    } catch (err) {
      if (currentBookEditor(editor)) {
        $('book-save-status').textContent = 'Not saved · retry when connected';
        $('book-error').textContent = err.message;
        $('retry-book-save').hidden = false;
      }
      throw err;
    } finally { editor.pending = null; }
  })();
  await editor.pending;
  // Serialize writes; newer input always follows an earlier request.
  if (currentBookEditor(editor) && JSON.stringify(reviewedBody('book')) !== editor.saved) await flushBookEdit();
}
async function finishBookEditing() {
  if (!bookEditor?.editing) return;
  await flushBookEdit();
  setBookEditing(false);
  refreshAll().catch(err=>toast(err.message));
}
async function closeBookDetails() {
  await finishBookEditing();
  $('book-dialog').close();
}
$('edit-book').addEventListener('click',()=>{setBookEditing(true);$('book-title').focus();});
bookFields.forEach(id=>$(id).addEventListener('input',()=>{
  if (!bookEditor?.editing) return;
  if (id==='book-genre') state.genreEdited=true;
  clearTimeout(bookEditor.timer);
  $('book-save-status').textContent = 'Unsaved changes…';
  bookEditor.timer = setTimeout(()=>flushBookEdit().catch(()=>{}),650);
}));
$('retry-book-save').addEventListener('click',()=>flushBookEdit().catch(()=>{}));
$('book-dialog').addEventListener('cancel',event=>{
  event.preventDefault();closeBookDetails().catch(err=>toast(err.message));
});
window.addEventListener('beforeunload',event=>{
  if (bookEditor?.editing && currentBookEditor(bookEditor) && (bookEditor.pending || JSON.stringify(reviewedBody('book'))!==bookEditor.saved)) {
    event.preventDefault();event.returnValue='';
  }
});

async function expandBookPhoto(photo) {
  const viewer=$('expanded-photo');
  viewer.removeAttribute('src');viewer.alt='Loading photo…';
  $('photo-dialog').showModal();
  $('photo-dialog').classList.remove('zoomed');$('photo-zoom').textContent='Zoom in';
  await loadImage(viewer,photo.url);
  if(viewer.hasAttribute('src'))viewer.alt=photo.view+' of the book';
}
$('photo-zoom').addEventListener('click',()=>{
  const zoomed=$('photo-dialog').classList.toggle('zoomed');
  $('photo-zoom').textContent=zoomed?'Fit photo':'Zoom in';
});
$('photo-dialog').addEventListener('close',()=>$('expanded-photo').removeAttribute('src'));

function renderScanProgress() {
  if (!$('scan-progress')) return;
  const scans=state.scans.filter(s=>(s.library_id || '')===(state.owner.startsWith('lib:')?state.owner.slice(4):''));
  const ready=scans.filter(s=>s.status==='ready').length;
  const failed=scans.filter(s=>s.status==='failed').length;
  const pending=scans.length-ready-failed;
  for(const id of ['scan-progress','library-progress']) {
    const root=$(id);root.replaceChildren();
    root.hidden=!state.me || !scans.length || (id==='scan-progress' && !['scan','queue'].includes(state.tab));
    if(root.hidden)continue;
    root.classList.toggle('compact-progress',id==='scan-progress');
    const copy=e('div');
    copy.append(e('strong','',ready?ready+' '+(ready===1?'book':'books')+' ready to review':failed?'A scan needs attention':'Your scans are in progress'));
    copy.append(e('p','small muted',[pending?pending+' processing or waiting':null,failed?failed+' need attention':null].filter(Boolean).join(' · ') || 'Check the details, then add them to your library.'));
    root.append(copy,button('Review scans','secondary',()=>navigate('queue')));
  }
}
// Keep the progress shortcut and page title in sync with navigation.
const baseNavigate = navigate;
navigate = function(tab) {
  baseNavigate(tab);
  if (['help','stats','admin'].includes(tab)) {
    const settings = document.querySelector('#workspace > .navigation [data-tab=settings]');
    settings.classList.add('active');settings.setAttribute('aria-pressed','true');
  }
  document.title=( {library:'Your library',scan:'Scan books',queue:'Review scans',help:'Help',settings:'Settings',friends:'Friends'}[tab] || 'BookBridge')+' · BookBridge';
  renderScanProgress();
};

const walkthroughSteps = [
  {icon:'01',title:'Your library starts here.',copy:'Turn the books on your shelves into a collection you can search. Start with a photo; every book you save will be waiting in Library.'},
  {icon:'02',title:'Scan a book. Keep going.',copy:'Take or upload a cover photo, or choose Shelf spines for up to five books. Add it to the queue and move to your next photo. The AI handles one queued scan at a time.'},
  {icon:'03',title:'A quick check before saving.',copy:'Open Scan → Review to check each result. Shelf photos produce a separate review for each book. Correct anything the AI missed, then save it to Library.'},
  {icon:'04',title:'A home for every book.',copy:'Library is your home after setup. Tap a book to view it, tap a photo to enlarge it, and press Edit to make changes that save automatically. Find this guide again in Settings → Help.'}
];
let walkthroughStep=0;
function guideKey(){return 'bookbridge-guide-v1:'+state.me.id;}
function guideSeen(){try{return localStorage.getItem(guideKey())==='done';}catch{return false;}}
function markGuideSeen(){try{localStorage.setItem(guideKey(),'done');}catch{}}
function renderWalkthrough(){
  const step=walkthroughSteps[walkthroughStep];
  $('walkthrough-count').textContent='WELCOME TO BOOKBRIDGE · '+(walkthroughStep+1)+' / '+walkthroughSteps.length;
  $('walkthrough-art').textContent=step.icon;
  $('walkthrough-title').textContent=step.title;
  $('walkthrough-copy').textContent=step.copy;
  $('walkthrough-back').hidden=walkthroughStep===0;
  $('walkthrough-next').textContent=walkthroughStep===walkthroughSteps.length-1?(state.ownBooks.length?'Open your library':'Scan your library'):'Next';
}
function offerWalkthrough(force=false){
  if(!state.me || (!force && guideSeen()))return;
  if(!force && state.ownBooks.length){markGuideSeen();return;}
  walkthroughStep=0;renderWalkthrough();$('walkthrough-dialog').showModal();
}
function endWalkthrough(start=false){
  markGuideSeen();$('walkthrough-dialog').close();
  if(start)navigate(state.ownBooks.length?'library':'scan');
}
$('walkthrough-back').addEventListener('click',()=>{walkthroughStep--;renderWalkthrough();});
$('walkthrough-next').addEventListener('click',()=>{
  if(walkthroughStep===walkthroughSteps.length-1)endWalkthrough(true);
  else{walkthroughStep++;renderWalkthrough();}
});
$('walkthrough-skip').addEventListener('click',()=>endWalkthrough());
$('walkthrough-dialog').addEventListener('cancel',event=>{event.preventDefault();endWalkthrough();});
$('replay-walkthrough').addEventListener('click',()=>offerWalkthrough(true));
$('profile-dialog').addEventListener('close',()=>{if(state.me?.profile_complete)offerWalkthrough();});
