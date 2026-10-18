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
      if(catalogView==='list'){row.append(makeBookCard([book,...copies.filter(b=>b.id!==book.id)],()=>onOpen(copies),()=>null));continue;}
      const spine=button('','book-spine',()=>onOpen(copies));
      const colors=['#2f4b3a','#6c4939','#4d5d54','#6b6040','#3d5660','#625063'];
      let hash=0;for(const char of book.title)hash=(Math.imul(hash,31)+char.charCodeAt(0))|0;
      spine.style.setProperty('--spine-color',colors[(hash>>>0)%colors.length]);
      spine.style.setProperty('--spine-height',(190+((hash>>>0)%4)*7)+'px');
      spine.append(e('span','spine-title',book.title));
      if(book.shelf_position)spine.append(e('span','spine-number',String(book.shelf_position)));
      spine.title=book.title+' — '+book.author+(book.shelf_label?' · '+book.shelf_label:'');
      spine.setAttribute('aria-label',book.title+' by '+book.author);row.append(spine);
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
