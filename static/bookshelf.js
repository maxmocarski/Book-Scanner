'use strict';

function bookshelfLocation(copies){
  const named=copies.filter(b=>b.shelf?.trim()).sort((a,b)=>a.shelf.localeCompare(b.shelf,undefined,{numeric:true,sensitivity:'base'}) || (a.shelf_position || 0)-(b.shelf_position || 0));
  return named[0] || [...copies].sort((a,b)=>(a.added_order || a.created || 0)-(b.added_order || b.created || 0))[0];
}
function renderBookshelf(root,groups,onOpen){
  applyCatalogView(root);root.classList.toggle('bookshelf-mode',catalogView!=='list');
  prepareShelfZoom(root);
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
    const row=e('div',catalogView==='shelves'?'spine-shelf':catalogView==='cards'?'digital-shelf':'shelf-list');
    for(const {book,copies} of section.entries){
      if(catalogView==='shelves') {
        const spine=button('', 'book-spine', ()=>onOpen(copies));
        const colors=['#2f4b3a','#6c4939','#4d5d54','#6b6040','#3d5660','#625063'];
        let hash=0;for(const char of book.title)hash=(Math.imul(hash,31)+char.charCodeAt(0))|0;
        spine.style.setProperty('--spine-color',colors[(hash>>>0)%colors.length]);
        spine.style.setProperty('--book-height',String(188+(hash>>>0)%4*7));
        spine.append(e('span','spine-title',book.title));
        spine.title=book.title+' — '+book.author;
        spine.setAttribute('aria-label',book.title+' by '+book.author);
        row.append(spine);continue;
      }
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


// Zoom changes spine dimensions so the books reflow into visible shelf rows.
let shelfZoom=1;
try { const saved=Number(localStorage.getItem('bookbridge-shelf-zoom')); if(saved>=.6 && saved<=1.8)shelfZoom=saved; } catch {}
function setShelfZoom(value, persist=true) {
  shelfZoom=Math.max(.6,Math.min(1.8,value));
  for(const id of ['book-grid','public-results']) $(id).style.setProperty('--shelf-zoom',shelfZoom);
  document.querySelectorAll('.shelf-zoom-value').forEach(n=>n.textContent=Math.round(shelfZoom*100)+'%');
  document.querySelectorAll('[data-shelf-zoom]').forEach(n=>n.disabled=n.dataset.shelfZoom==='out'?shelfZoom<=.6:n.dataset.shelfZoom==='in'?shelfZoom>=1.8:false);
  if(persist)try{localStorage.setItem('bookbridge-shelf-zoom',String(shelfZoom));}catch{}
}
function prepareShelfZoom(root) {
  root.style.setProperty('--shelf-zoom',shelfZoom);
  if(root.dataset.zoomReady)return;
  root.dataset.zoomReady='true';
  let pinch=null, suppressUntil=0;
  const distance=touches=>Math.hypot(touches[0].clientX-touches[1].clientX,touches[0].clientY-touches[1].clientY);
  root.addEventListener('touchstart',event=>{
    if(catalogView==='shelves' && event.touches.length===2) {
      pinch={distance:Math.max(1,distance(event.touches)),zoom:shelfZoom};
      suppressUntil=Date.now()+500;event.preventDefault();
    }
  },{passive:false});
  root.addEventListener('touchmove',event=>{
    if(!pinch || event.touches.length!==2 || catalogView!=='shelves')return;
    event.preventDefault();suppressUntil=Date.now()+500;
    setShelfZoom(pinch.zoom*distance(event.touches)/pinch.distance,false);
  },{passive:false});
  const end=event=>{if(pinch && event.touches.length<2){pinch=null;suppressUntil=Date.now()+500;setShelfZoom(shelfZoom);}};
  root.addEventListener('touchend',end);root.addEventListener('touchcancel',end);
  root.addEventListener('click',event=>{if(Date.now()<suppressUntil){event.preventDefault();event.stopImmediatePropagation();}},true);
}
for(const control of document.querySelectorAll('[data-shelf-zoom]'))control.addEventListener('click',()=>{
  setShelfZoom(control.dataset.shelfZoom==='reset'?1:shelfZoom+(control.dataset.shelfZoom==='in'?.1:-.1));
});
setShelfZoom(shelfZoom,false);
