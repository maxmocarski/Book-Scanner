'use strict';

let catalogView='cards';
try{catalogView=localStorage.getItem('bookbridge-catalog-view')==='list'?'list':'cards';}catch{}
function applyCatalogView(root){
  root.classList.toggle('catalog-list',catalogView==='list');
  document.querySelectorAll('[data-catalog-view]').forEach(control=>{
    const active=control.dataset.catalogView===catalogView;
    control.setAttribute('aria-pressed',String(active));control.classList.toggle('active',active);
  });
}
function catalogShelf(copies){
  const shelves=[...new Set(copies.map(book=>book.shelf_label || book.shelf).filter(Boolean))];
  shelves.sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  return shelves;
}
function makeBookCard(copies,onOpen,photo){
  const book=copies[0],card=button('','book-card',onOpen);
  if(catalogView==='cards'){
    const cover=e('div','book-cover-area');
    const fallback=e('span','cover-fallback',book.title);fallback.setAttribute('aria-hidden','true');cover.append(fallback);
    const img=photo(book);
    if(img){
      img.classList.add('catalog-cover');
      img.addEventListener('load',()=>{img.classList.add('loaded');fallback.hidden=true;},{once:true});
      img.addEventListener('error',()=>img.remove(),{once:true});
      if(img.complete && img.naturalWidth){img.classList.add('loaded');fallback.hidden=true;}
      cover.append(img);
    }
    card.append(cover);
  }
  const info=e('div','book-card-info');
  const title=e('h3','',book.title);title.title=book.title;
  const author=e('p','card-author',book.author);author.title=book.author;
  info.append(title,author);
  const shelves=catalogShelf(copies);
  info.append(e('p','card-shelf',shelves[0] || 'Shelf not set'));
  if(shelves.length>1)info.append(e('p','card-location-hint','More locations inside'));
  card.append(info);card.setAttribute('aria-label',book.title+' by '+book.author);
  return card;
}
function makeLibraryCard(library,onOpen){
  const card=e('article','library-card');
  if(catalogView==='cards'){
    const symbol=e('div','library-card-symbol');symbol.setAttribute('aria-hidden','true');
    const icon=e('img');icon.src='/static/icon.svg';icon.alt='';symbol.append(icon);card.append(symbol);
  }
  const info=e('div','library-card-info');
  info.append(e('span','library-card-kicker','Public shared library'),e('h2','',library.name),button('View books','secondary',onOpen));
  card.append(info);return card;
}
for(const control of document.querySelectorAll('[data-catalog-view]'))control.addEventListener('click',()=>{
  catalogView=control.dataset.catalogView;
  try{localStorage.setItem('bookbridge-catalog-view',catalogView);}catch{}
  applyCatalogView($('book-grid'));applyCatalogView($('public-results'));
  if(state.me && state.tab==='library')renderLibrary();
  if(state.tab==='public')renderPublic();
});
applyCatalogView($('book-grid'));applyCatalogView($('public-results'));
