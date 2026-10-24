'use strict';

function bookshelfLocation(copies){
  const named=copies.filter(b=>b.shelf?.trim()).sort((a,b)=>a.shelf.localeCompare(b.shelf,undefined,{numeric:true,sensitivity:'base'}) || (a.shelf_position || 0)-(b.shelf_position || 0));
  return named[0] || [...copies].sort((a,b)=>(a.added_order || a.created || 0)-(b.added_order || b.created || 0))[0];
}
function renderBookshelf(root,groups,onOpen){
  applyCatalogView(root);root.classList.toggle('bookshelf-mode',catalogView==='cards');
  const sections=new Map();
  for(const copies of groups){
    const book=bookshelfLocation(copies),name=(book.shelf || '').trim(),key=name.toLocaleLowerCase();
    if(!sections.has(key))sections.set(key,{name,entries:[]});
    sections.get(key).entries.push({book,copies});
  }
  const ordered=[...sections.values()].sort((a,b)=>a.name&&b.name?a.name.localeCompare(b.name,undefined,{numeric:true}):a.name?-1:b.name?1:0);
  for(const section of ordered){
    section.entries.sort((a,b)=>section.name?(a.book.shelf_position || Number.MAX_SAFE_INTEGER)-(b.book.shelf_position || Number.MAX_SAFE_INTEGER) || (a.book.added_order || 0)-(b.book.added_order || 0):(a.book.added_order || a.book.created || 0)-(b.book.added_order || b.book.created || 0));
    const shelf=e('section','shelf-section');shelf.append(e('h2','shelf-heading',section.name || 'Miscellaneous'));
    if(!section.name)shelf.append(e('p','small muted','No shelf assigned · added in library order'));
    const row=e('div',catalogView==='cards'?'digital-shelf':'shelf-list');
    for(const {book,copies} of section.entries){
      row.append(makeBookCard([book,...copies.filter(b=>b.id!==book.id)],()=>onOpen(copies), item => {
        const photo = item.images.find(p=>p.view==='front') || item.images[0];
        return photo ? (root.id==='public-results' ? publicPhoto(photo,'') : image(photo.url,'',item.title+' cover')) : null;
      }));
    }
    shelf.append(row);root.append(shelf);
  }
}
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

