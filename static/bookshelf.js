'use strict';

function bookshelfLocation(copies){
  const named=copies.filter(b=>b.shelf?.trim()).sort((a,b)=>a.shelf.localeCompare(b.shelf,undefined,{numeric:true,sensitivity:'base'}) || (a.shelf_position || 0)-(b.shelf_position || 0));
  return named[0] || [...copies].sort((a,b)=>(a.added_order || a.created || 0)-(b.added_order || b.created || 0))[0];
}
let shelfSort = 'custom', shelfZoom = 100;
function shelfPreferenceKey(){return 'bookbridge-shelves:'+ (state.me?.id || 'public')+':'+(state.owner || 'self');}
function readShelfPreferences(){
  try {const value=JSON.parse(localStorage.getItem(shelfPreferenceKey()) || '{}');shelfSort=['custom','title','genre','date'].includes(value.sort)?value.sort:'custom';shelfZoom=Math.min(150,Math.max(65,Number(value.zoom)||100));}catch{shelfSort='custom';shelfZoom=100;}
}
function saveShelfPreferences(){try{localStorage.setItem(shelfPreferenceKey(),JSON.stringify({sort:shelfSort,zoom:shelfZoom}));}catch{}}
function renderBookshelf(root,groups,onOpen){
  readShelfPreferences();
  $('shelf-sort').value=shelfSort;$('shelf-zoom').value=shelfZoom;$('shelf-zoom-value').textContent=shelfZoom+'%';
  const writable=!state.owner || state.owner===state.me?.id || (state.libraries || []).some(l=>'lib:'+l.id===state.owner && l.owner===state.me?.id);
  $('lookup-genres').hidden=root.id==='public-results' || !writable;
  applyCatalogView(root);root.classList.toggle('bookshelf-mode',catalogView==='cards');
  root.style.setProperty('--shelf-book-width',Math.round(100*shelfZoom/100)+'px');
  const sections=new Map();
  const entries=groups.map(copies=>({book:bookshelfLocation(copies),copies}));
  const title=(a,b)=>a.book.title.localeCompare(b.book.title,undefined,{numeric:true,sensitivity:'base'}) || String(a.book.id).localeCompare(String(b.book.id));
  entries.sort((a,b)=>shelfSort==='date'?(b.book.added_order || b.book.created || 0)-(a.book.added_order || a.book.created || 0) || title(a,b):title(a,b));
  for(const entry of entries){
    const name=shelfSort==='custom'?(entry.book.shelf || '').trim() || 'Unassigned':shelfSort==='genre'?(entry.book.genre || '').trim() || 'Uncategorized':shelfSort==='date'?'Recently added':'Titles · A–Z';
    const key=name.toLocaleLowerCase();if(!sections.has(key))sections.set(key,{name,entries:[]});sections.get(key).entries.push(entry);
  }
  const ordered=[...sections.values()];
  if(['genre','custom'].includes(shelfSort))ordered.sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
  for(const section of ordered){
    if(shelfSort==='custom')section.entries.sort((a,b)=>(a.book.shelf_position || Number.MAX_SAFE_INTEGER)-(b.book.shelf_position || Number.MAX_SAFE_INTEGER) || title(a,b));
    const shelf=e('section','shelf-section');shelf.append(e('h2','shelf-heading',section.name));
    const row=e('div',catalogView==='cards'?'digital-shelf':'shelf-list');
    for(const {book,copies} of section.entries){
      const card=makeBookCard([book,...copies.filter(b=>b.id!==book.id)],()=>onOpen(copies),item=>{
        const photo=item.images.find(p=>p.view==='front') || item.images[0];
        return photo?(root.id==='public-results'?publicPhoto(photo,''):image(photo.url,'',item.title+' cover')):null;
      });
      card.dataset.bookId=book.id;
      card.querySelector('.book-card-info').append(e('p','card-genre',book.genre || 'Uncategorized'));
      row.append(card);
    }
    shelf.append(row);root.append(shelf);
  }
}
function rearrangeShelves(){
  const root=$('book-grid'),before=new Map([...root.querySelectorAll('[data-book-id]')].map(el=>[el.dataset.bookId,el.getBoundingClientRect()]));
  renderLibrary();
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  root.querySelectorAll('[data-book-id]').forEach(el=>{
    const old=before.get(el.dataset.bookId);if(!old)return;const next=el.getBoundingClientRect();
    el.animate([{transform:`translate(${old.left-next.left}px,${old.top-next.top}px)`},{transform:'translate(0,0)'}],{duration:550,easing:'cubic-bezier(.2,.8,.2,1)'});
  });
}
$('shelf-sort').addEventListener('change',event=>{shelfSort=event.target.value;saveShelfPreferences();rearrangeShelves();});
$('shelf-zoom').addEventListener('input',event=>{shelfZoom=Number(event.target.value);saveShelfPreferences();rearrangeShelves();});
let findingGenres=false;
$('lookup-genres').addEventListener('click',async()=>{
  if(findingGenres)return;findingGenres=true;
  const account=state.me?.id,owner=state.owner,epoch=state.epoch;
  const pending=state.books.filter(b=>!b.genre?.trim());
  $('lookup-genres').disabled=true;let completed=0,failed=0;
  try{
    for(const book of pending){
      if(state.me?.id!==account || state.owner!==owner || state.epoch!==epoch)break;
      $('genre-status').textContent=`Looking up genres · ${completed+failed+1} of ${pending.length}`;
      try{
        const updated=await api('/books/'+encodeURIComponent(book.id)+'/genre',{method:'POST'});
        if(state.me?.id!==account || state.owner!==owner || state.epoch!==epoch)break;
        Object.assign(book,updated);completed++;rearrangeShelves();
      }catch{failed++;}
    }
    $('genre-status').textContent=pending.length?`${completed} books checked${failed?' · '+failed+' unavailable; retry or enter manually':''}. Review AI genres in book details.`:'Every book already has a genre. You can edit genres in book details.';
  }finally{findingGenres=false;$('lookup-genres').disabled=false;}
});
function syncLibraryDock(){
  const select=$('library-owner');
  select.value=state.tab==='public'?'__public__':state.owner;
  $('library-dock').hidden=!state.me;
  $('scan-tabs').hidden=!state.me || !['scan','queue'].includes(state.tab);
  $('friends-tabs').hidden=!state.me || !['friends','trades'].includes(state.tab);
}
function updateScanMode(){
  const shelf=$('scan-mode-kind').value==='shelf';
  if(state.busyUpload)return;
  clearPhotos();state.view='front';$('photo-input').dataset.view='front';$('photo-input').value='';
  $('shelf-photo-options').hidden=!shelf;
  $('scan-help').textContent=shelf?'Photograph 1–5 upright book spines. Each book gets its own review.':'Photograph the cover. The spine and back are optional.';
  $('scan-limit').hidden=!shelf;
  renderPhotos();
}
$('scan-mode-kind').addEventListener('change',updateScanMode);


