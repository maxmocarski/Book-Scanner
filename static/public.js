'use strict';

const publicCatalog={selected:'',library:null,items:[],next:null,serial:0};
function resetPublic(){
  publicCatalog.serial++;
  publicCatalog.selected='';publicCatalog.library=null;publicCatalog.items=[];publicCatalog.next=null;
  $('public-results').replaceChildren();$('public-search').value='';$('public-more').hidden=true;
  $('public-book-dialog').close();$('public-book-photos').replaceChildren();
}
function publicError(err){
  $('public-results').replaceChildren();$('public-more').hidden=true;
  $('public-status').textContent=err.message;
  $('public-book-dialog').close();$('public-book-photos').replaceChildren();
}
async function refreshPublic(append=false){
  const serial=++publicCatalog.serial, selected=publicCatalog.selected;
  const offset=append ? publicCatalog.next : 0;
  if(append && offset===null)return;
  $('public-more').disabled=true;
  $('public-back').hidden=!selected;
  $('public-search').placeholder=selected?'Search title, author, ISBN or shelf':'Search public libraries';
  if(!append){publicCatalog.items=[];$('public-results').replaceChildren();$('public-status').textContent='Loading…';$('public-book-dialog').close();$('public-book-photos').replaceChildren();}
  try{
    const path=selected?'/public/libraries/'+encodeURIComponent(selected)+'/books':'/public/libraries';
    const data=await api(path+'?q='+encodeURIComponent($('public-search').value.trim())+'&offset='+offset,{authenticated:false});
    if(serial!==publicCatalog.serial || selected!==publicCatalog.selected || state.tab!=='public')return;
    publicCatalog.library=data.library || null;
    publicCatalog.items.push(...(selected?data.books:data.libraries));publicCatalog.next=data.next_offset;
    renderPublic();
  }finally{if(serial===publicCatalog.serial)$('public-more').disabled=false;}
}
function publicPhoto(photo,cls){
  const img=e('img',cls);img.src=photo.url;img.alt=photo.view+' of book';img.loading='lazy';img.referrerPolicy='no-referrer';
  img.addEventListener('error',()=>img.remove(),{once:true});return img;
}
function renderPublic(){
  const selected=publicCatalog.selected,root=$('public-results');root.replaceChildren();applyCatalogView(root);
  $('public-heading').textContent=publicCatalog.library?.name || 'Public libraries';
  $('public-filters').querySelector('summary').textContent=selected?'Search and filter books':'Search and filter libraries';
  $('public-description').textContent=selected?'Public catalog · viewing only':'Browse shared collections. No account needed.';
  $('public-status').textContent=publicCatalog.items.length ? publicCatalog.items.length+(selected?(publicCatalog.items.length===1?' book loaded':' books loaded'):(publicCatalog.items.length===1?' library loaded':' libraries loaded')) : selected?'No saved books match your search.':'No public libraries match your search.';
  $('public-more').hidden=publicCatalog.next===null;
  root.classList.remove('bookshelf-mode');
  if(selected){renderBookshelf(root,groupCopies(publicCatalog.items),openPublicCopies);return;}
  const entries=publicCatalog.items;
  for(const entry of entries){
    const copies=selected?entry:[];
    const item=selected?copies[0]:entry;
    if(!selected){
      root.append(makeLibraryCard(item,()=>{
        publicCatalog.selected=item.id;publicCatalog.library=item;$('public-search').value='';closeSections();refreshPublic().catch(publicError);
      }));
    }else{
      root.append(makeBookCard(copies,()=>openPublicCopies(copies),book=>book.images.length?publicPhoto(book.images[0],''):null));
    }
  }
}
function openPublicCopies(copies){
  $('public-book-copies').textContent=copies.length+(copies.length===1?' copy':' copies');
  const select=$('public-copy');select.replaceChildren();
  copies.forEach((book,index)=>{const option=e('option','','Copy '+(index+1)+(book.shelf_label?' · '+book.shelf_label:''));option.value=String(index);select.append(option);});
  $('public-copy-label').hidden=copies.length<2;
  select.onchange=()=>openPublicBook(copies[Number(select.value)]);
  openPublicBook(copies[0]);
}
function openPublicBook(book){
  $('public-book-title').textContent=book.title;$('public-book-author').textContent=book.author;
  $('public-book-isbn').textContent=book.isbn?'ISBN '+book.isbn:'ISBN not recorded';
  $('public-book-shelf').textContent=book.shelf_label?'Shelf: '+book.shelf_label:'';
  $('public-book-photos').replaceChildren(...book.images.map(photo=>publicPhoto(photo,'')));
  if(!$('public-book-dialog').open)$('public-book-dialog').showModal();
}
$('guest-signin').addEventListener('click',()=>{
  navigate('auth');$('auth').hidden=false;$('guest-signin').classList.add('active');$('guest-signin').setAttribute('aria-pressed','true');
});
$('public-search-form').addEventListener('submit',event=>{event.preventDefault();refreshPublic().catch(publicError);});
$('public-back').addEventListener('click',()=>{publicCatalog.selected='';publicCatalog.library=null;$('public-search').value='';closeSections();refreshPublic().catch(publicError);});
$('public-more').addEventListener('click',()=>refreshPublic(true).catch(publicError));
