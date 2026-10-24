'use strict';
const GENRE_CHOICES=["Fiction", "Mystery & thriller", "Science fiction", "Fantasy", "Romance", "Historical fiction", "Horror", "Children’s books", "Young adult", "Biography & memoir", "History", "Science & nature", "Technology", "Business & economics", "Self-help", "Philosophy & religion", "Poetry", "Drama", "Travel", "Cooking", "Art & music", "Health & fitness", "Education", "Reference", "Uncategorized"];

const genreState={owner:null,signature:null,busy:false,submitting:false,pending:0};
function resetGenres(){genreState.owner=null;genreState.signature=null;genreState.busy=false;genreState.submitting=false;genreState.pending=0;$('genre-filter').value='';$('genre-status').textContent='';}
function genreMatches(book){const selected=$('genre-filter').value;return !selected || (selected==='__missing__'?!book.genre:book.genre===selected);}
function canCheckGenres(){return !state.owner || state.owner.startsWith('lib:') && (state.libraries || []).some(l=>'lib:'+l.id===state.owner && l.owner===state.me?.id);}
function renderGenreFilters(){
  const selected=$('genre-filter').value,choices=[...new Set(state.books.map(b=>b.genre).filter(Boolean))].sort();
  $('genre-filter').replaceChildren(new Option('All genres',''),new Option('Not checked','__missing__'),...choices.map(g=>new Option(g,g)));
  // Retain an active filter when the last matching book is edited or removed.
  if(selected && selected!=='__missing__' && !choices.includes(selected))$('genre-filter').add(new Option(selected,selected));
  $('genre-filter').value=selected;
  $('genre-check').hidden=!canCheckGenres();
  $('genre-check').disabled=genreState.submitting || genreState.pending>0 || !state.books.some(b=>!b.genre);
  if(genreState.owner!==state.owner){genreState.owner=state.owner;genreState.signature=null;genreState.pending=0;$('genre-status').textContent='';}
}
function fillBookGenres(value){
  $('book-genre').replaceChildren(new Option('Not checked',''),...GENRE_CHOICES.map(g=>new Option(g,g)));
  if(value && !GENRE_CHOICES.includes(value))$('book-genre').add(new Option(value,value));
  $('book-genre').value=value;
}
function genrePath(){return '/genre-checks'+(state.owner.startsWith('lib:')?'?library_id='+encodeURIComponent(state.owner.slice(4)):'');}
async function refreshGenreStatus(){
  if(!state.me || genreState.busy || (state.owner && !state.owner.startsWith('lib:')))return;
  const owner=state.owner,epoch=state.epoch;
  genreState.busy=true;
  try {
    const result=await api(genrePath());
    if(owner!==state.owner || epoch!==state.epoch)return;
    const c=result.counts,pending=c.queued+c.checking;
    genreState.pending=pending;
    $('genre-status').textContent=pending?pending+' genre '+(pending===1?'check':'checks')+' remaining · runs after book scans.':c.failed?c.failed+' checks need another try. Check Ollama, then use the button to retry missing genres.':c.done?'Genre checks complete. AI labels can be corrected with Edit.':'';
    if(!pending && !result.missing && state.books.length)$('genre-status').textContent='All books have a genre. You can correct labels with Edit.';
    $('genre-check').hidden=!result.can_check;
    $('genre-check').disabled=genreState.submitting || !result.missing || pending>0;
    $('genre-check').textContent=pending?'Checking genres…':c.failed && result.missing?'Retry missing genres':'Check genres with AI';
    const signature=JSON.stringify([owner,c.done,c.failed]);
    const changed=genreState.signature!==signature;
    genreState.signature=signature;
    if(changed && !bookEditor?.editing)await refreshAll();
  } finally {if(epoch===state.epoch)genreState.busy=false;}
}
$('genre-filter').addEventListener('change',renderLibrary);
$('genre-check').addEventListener('click',async()=>{
  if(genreState.submitting)return;
  genreState.submitting=true;$('genre-check').disabled=true;
  try {
    const result=await api(genrePath(),{method:'POST'});
    $('genre-status').textContent=result.queued?result.queued+' books queued for genre checking.':'No new books need a genre check.';
    genreState.signature=null;
    await refreshGenreStatus();
  }catch(err){$('genre-status').textContent=err.message;}
  finally{genreState.submitting=false;await refreshGenreStatus().catch(()=>{});}
});
