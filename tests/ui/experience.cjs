// Disposable mock_server.py only. Uses real API/database with fake inference.
const {chromium,devices}=require('playwright');
const assert=require('node:assert/strict');
const base=process.argv[2] || 'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({...devices['iPhone 13']});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const username='experience_'+Date.now();
  async function json(path,body,method){const token=await page.evaluate(()=>sessionStorage.getItem('bookbridge-token'));const form=body instanceof FormData;const r=await fetch(base+path,{method:method || (body?'POST':'GET'),headers:{Authorization:'Bearer '+token,...(body&&!form?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});const result=r.status===204?null:await r.json();assert(r.ok,JSON.stringify(result));return result;}
  const text=(id,value)=>page.waitForFunction(([id,value])=>document.getElementById(id)?.textContent.includes(value),[id,value]);
  const nav=tab=>page.locator('#workspace > .navigation [data-tab='+tab+']').click();
  await page.goto(base);await page.locator('#auth-toggle').click();await page.locator('#auth-name').fill(username);await page.locator('#auth-password').fill('testing123');await page.locator('#auth-submit').click();
  await page.locator('#profile-dialog').waitFor({state:'visible'});await page.locator('#profile-first').fill('Phone');await page.locator('#profile-last').fill('Reader');await page.locator('#profile-form button').click();
  await page.locator('#walkthrough-dialog').waitFor({state:'visible'});
  for(let i=0;i<3;i++)await page.locator('#walkthrough-next').click();
  assert.equal(await page.locator('#walkthrough-next').textContent(),'Scan your library');await page.locator('#walkthrough-next').click();await page.locator('#page-scan').waitFor({state:'visible'});
  for(const width of [390,1280]) {
    await page.setViewportSize({width,height:844});
    const order=await page.evaluate(()=>['camera-video','queue-book','scan-mode-kind','photo-slots','scan-shelf'].map(id=>document.getElementById(id).getBoundingClientRect().top));
    assert(order.every((y,i)=>i===0 || y>order[i-1]),'Camera, queue, mode, photos, shelf order');
  }
  await page.setViewportSize({width:390,height:844});
  const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=300;c.height=420;const x=c.getContext('2d');x.fillStyle='#314d3c';x.fillRect(0,0,300,420);x.fillStyle='#fffae9';x.font='28px serif';x.fillText('A GOOD STORY',30,180);return c.toDataURL().split(',')[1];}),'base64');
  await page.locator('#photo-input').setInputFiles({name:'cover.png',mimeType:'image/png',buffer:png});await page.locator('#queue-book').click();await text('scan-feedback','queued');
  await page.waitForFunction(()=>document.getElementById('scan-progress').textContent.includes('ready to review'));
  await page.locator('#scan-progress button').click();await page.locator('#queue-list .primary').first().click();await page.locator('#review-dialog').waitFor({state:'visible'});await page.locator('#review-book-title').fill('A Good Story');await page.locator('#review-author').fill('A. Reader');await page.locator('#review-form .primary').click();await page.locator('#review-dialog').waitFor({state:'hidden'});
  await nav('library');await page.locator('#book-grid .book-card').click();await page.locator('#book-dialog').waitFor({state:'visible'});
  assert(await page.locator('#book-title').getAttribute('readonly')!==null);assert(!await page.locator('#book-own-actions').isVisible());
  await page.locator('#book-photos button').first().click();await page.locator('#photo-dialog').waitFor({state:'visible'});await page.waitForFunction(()=>document.getElementById('expanded-photo').naturalWidth>0);await page.locator('#photo-zoom').click();assert(await page.locator('#photo-dialog').evaluate(el=>el.classList.contains('zoomed')));await page.locator('[data-close=photo-dialog]').click();
  await page.locator('#edit-book').click();await page.locator('#book-title').fill('Edited automatically');await text('book-save-status','All changes saved');assert.equal((await json('/books'))[0].title,'Edited automatically');
  // Closing flushes the debounce instead of dropping a final keystroke.
  await page.locator('#book-author').fill('New Author');await page.locator('[data-close=book-dialog]').click();await page.locator('#book-dialog').waitFor({state:'hidden'});assert.equal((await json('/books'))[0].author,'New Author');
  await page.locator('#book-grid .book-card').click();assert(await page.locator('#book-title').getAttribute('readonly')!==null);await page.locator('#edit-book').click();
  // A failed write retains the draft; Retry saves it.
  await page.route('**/books/*',route=>route.request().method()==='PATCH'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Offline test'})}):route.continue());
  await page.locator('#book-title').fill('Retry saved title');await text('book-save-status','Not saved');await page.locator('[data-close=book-dialog]').click();assert(await page.locator('#book-dialog').isVisible());assert.equal(await page.locator('#book-title').inputValue(),'Retry saved title');
  await page.unroute('**/books/*');await page.locator('#retry-book-save').click();await text('book-save-status','All changes saved');
  await page.locator('#book-title').fill('');await page.locator('[data-close=book-dialog]').click();assert(await page.locator('#book-dialog').isVisible());await page.locator('#book-title').fill('Final title');await page.locator('#book-own-actions .primary').click();await text('book-save-status','Read-only');await page.locator('[data-close=book-dialog]').click();
  // Multiple edits arriving during a slow write are serialized.
  await page.locator('#book-grid .book-card').click();await page.locator('#edit-book').click();
  let writes=0;await page.route('**/books/*',async route=>{if(route.request().method()==='PATCH'){writes++;await new Promise(r=>setTimeout(r,700));}await route.continue();});
  await page.locator('#book-title').fill('Intermediate');await page.waitForTimeout(750);await page.locator('#book-title').fill('Last edit wins');await page.locator('[data-close=book-dialog]').click();await page.locator('#book-dialog').waitFor({state:'hidden'});assert.equal((await json('/books'))[0].title,'Last edit wins');assert(writes>=2);await page.unroute('**/books/*');
  // Shelf photo becomes separate reviews and the queue accepts another upload.
  await nav('scan');await page.locator('#scan-mode-kind').selectOption('shelf');await page.locator('#shelf-book-count').selectOption('3');await page.locator('#photo-input').setInputFiles({name:'shelf.png',mimeType:'image/png',buffer:png});await page.locator('#queue-book').click();await text('scan-feedback','queued');
  await page.locator('#photo-input').setInputFiles({name:'shelf2.png',mimeType:'image/png',buffer:png});await page.locator('#queue-book').click();await text('scan-feedback','queued');
  await page.locator('#scan-tabs [data-tab=queue]').click();await page.waitForFunction(()=>document.querySelectorAll('#queue-list button.primary').length===6);
  await page.locator('#queue-list button.primary').first().click();await page.locator('#review-dialog').waitFor({state:'visible'});assert((await page.locator('#review-book-title').inputValue()).startsWith('Shelf Book'));await page.locator('[data-close=review-dialog]').click();
  await nav('settings');await page.locator('[data-tab=help]').click();await page.locator('#replay-walkthrough').click();await page.locator('#walkthrough-dialog').waitFor({state:'visible'});await page.locator('#walkthrough-skip').click();
  await page.reload();await page.locator('#page-library').waitFor({state:'visible'});assert(!await page.locator('#walkthrough-dialog').isVisible());
  for(const [width,height] of [[320,568],[390,844],[430,932],[844,390],[1280,900]]){
   await page.setViewportSize({width,height});
   for(const tab of ['library','scan','settings']){await nav(tab);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow '+width+' '+tab);}
  }
  await page.setViewportSize({width:390,height:844});await nav('library');await page.locator('#book-grid .book-card').scrollIntoViewIfNeeded();await page.waitForTimeout(250);assert(await page.locator('#book-grid .book-card h3').isVisible());await page.screenshot({path:'/tmp/bookbridge-library.png',fullPage:true});await nav('scan');await page.screenshot({path:'/tmp/bookbridge-scan.png',fullPage:true});
  // Optional shelves use text spines and zoom without changing book data.
  for(const scan of await json('/scans?limit=500')) {
    if(scan.status==='ready')await json('/scans/'+scan.id+'/save',{title:scan.metadata.title,author:scan.metadata.author});
  }
  await nav('library');await page.waitForFunction(()=>document.querySelectorAll('#book-grid .book-card').length===4);
  assert.equal(await page.locator('#page-library [data-catalog-view=cards]').getAttribute('aria-pressed'),'true');
  await page.locator('#page-library [data-catalog-view=shelves]').click();
  assert.equal(await page.locator('#book-grid img').count(),0);
  assert.equal(await page.locator('#book-grid .book-spine').count(),4);
  assert(!await page.locator('#page-library [data-shelf-zoom=in]').isVisible());
  await page.locator('#page-library .trade-filter summary').click();
  await page.locator('#page-library [data-shelf-zoom=reset]').click();
  const spineHeight=await page.locator('#book-grid .book-spine').first().evaluate(el=>el.offsetHeight);
  await page.locator('#page-library [data-shelf-zoom=in]').click();
  assert(await page.locator('#book-grid .book-spine').first().evaluate(el=>el.offsetHeight)>spineHeight);
  await page.locator('#page-library [data-shelf-zoom=reset]').click();
  await page.locator('#book-grid').evaluate(el=>el.scrollIntoView({block:'start'}));
  const rect=await page.locator('#book-grid').boundingBox();
  const y=Math.max(20,rect.y+70),x=rect.x+120;
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:x-35,y},{x:x+35,y}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-55,y},{x:x+55,y}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  assert(await page.locator('#book-grid .book-spine').first().evaluate(el=>el.offsetHeight)>spineHeight,'Pinch grows spines');
  assert(!await page.locator('#book-dialog').isVisible(),'Pinch must not open a book');
  await page.waitForTimeout(550);
  await page.locator('#book-grid .book-spine').first().click();
  await page.locator('#book-dialog').waitFor({state:'visible'});await page.locator('[data-close=book-dialog]').click();
  for(const width of [320,390,1280]) {
    await page.setViewportSize({width,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Shelf overflow '+width);
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('#page-library [data-shelf-zoom=reset]').click();
  await page.locator('#page-library .trade-filter summary').click();
  await page.locator('#book-grid').evaluate(el=>el.scrollIntoView({block:'start'}));
  await page.screenshot({path:'/tmp/bookbridge-shelves.png'});
  await page.locator('#page-library [data-catalog-view=list]').click();assert.equal(await page.locator('#book-grid img').count(),0);
  await page.locator('#page-library [data-catalog-view=cards]').click();assert.equal(await page.locator('#book-grid .book-card').count(),4);
  await page.locator('#page-library [data-catalog-view=shelves]').click();await page.reload();
  await page.locator('#book-grid .book-card').first().waitFor();assert.equal(await page.locator('#book-grid .book-spine').count(),0,'Reload defaults to Covers');
  // Genre checks persist and the filter applies to each display mode.
  await page.locator('#page-library .trade-filter summary').click();
  await page.locator('#genre-check').click();
  await page.waitForFunction(()=>[...document.querySelectorAll('#genre-filter option')].some(o=>o.value==='Fantasy'));
  await page.waitForFunction(()=>document.querySelector('#genre-status').textContent.includes('All books have a genre'));
  assert((await json('/books')).every(b=>b.genre));
  await page.locator('#genre-filter').selectOption('Fantasy');
  assert.equal(await page.locator('#book-grid .book-card').count(),3);
  await page.locator('#page-library [data-catalog-view=shelves]').click();assert.equal(await page.locator('#book-grid .book-spine').count(),3);
  await page.locator('#page-library [data-catalog-view=list]').click();assert.equal(await page.locator('#book-grid .book-card').count(),3);
  await page.locator('#genre-filter').selectOption('Fiction');await page.locator('#book-grid .book-card').click();
  assert(await page.locator('#book-genre').isDisabled());assert.equal(await page.locator('#book-genre').inputValue(),'Fiction');
  await page.locator('#edit-book').click();await page.locator('#book-genre').selectOption('History');await text('book-save-status','All changes saved');
  await page.locator('[data-close=book-dialog]').click();
  await page.locator('#genre-filter').selectOption('History');assert.equal(await page.locator('#book-grid .book-card').count(),1);
  await page.reload();await page.locator('#book-grid .book-card').first().waitFor();
  await page.locator('#page-library .trade-filter summary').click();await page.locator('#genre-filter').selectOption('History');assert.equal(await page.locator('#book-grid .book-card').count(),1);
  await page.screenshot({path:'/tmp/bookbridge-genres.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS: onboarding, library landing, uploads, shelf review, locked details, cover zoom, autosave, close flush, failure/retry, validation, serialized writes, help five viewport sizes, camera-first order, shelf spines, pinch/button zoom, Covers default, AI genres, genre filters and manual genre autosave.');
 } finally {await browser.close();}
})().catch(err=>{console.error(err);process.exit(1);});
