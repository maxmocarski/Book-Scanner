// Only run against the disposable mock_server.py instance.
const {chromium,devices}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const base=process.argv[2] || 'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--use-gl=angle','--use-angle=swiftshader']});
 try{
  const context=await browser.newContext({...devices['iPhone 13']});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function api(path,token,body){const form=body instanceof FormData;const response=await fetch(base+path,{method:body?'POST':'GET',headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body&&!form?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});const result=await response.json();assert(response.ok,JSON.stringify(result));return result;}
  const manager=await api('/auth/register',null,{username:'manager_ui',password:'testing123'});const token=manager.access_token;await api('/me/profile-setup',token,{first_name:'Max',last_name:'Reader'});
  const library=await api('/libraries',token,{name:'Town Lending Library',is_public:true});await api('/libraries',token,{name:'School Reading Room',is_public:true});
  await page.goto(base);const titles=[['The Hobbit','J. R. R. Tolkien','9780261103344','#284d3a'],['A Walk in the Woods','Bill Bryson',null,'#bca46d'],['The Secret Garden','Frances Hodgson Burnett',null,'#685e47']];
  for(const libraryId of [library.id,''])for(const [index,row] of [...titles,titles[0]].entries()){
   const [title,author,isbn,color]=row;
   const png=await page.evaluate(({title,color})=>{const c=document.createElement('canvas');c.width=220;c.height=330;const x=c.getContext('2d');x.fillStyle=color;x.fillRect(0,0,220,330);x.strokeStyle='#eee8d0';x.strokeRect(15,15,190,300);x.fillStyle='#fff9df';x.font='22px Georgia';x.textAlign='center';const words=title.split(' ');words.forEach((w,i)=>x.fillText(w,110,110+i*30));return c.toDataURL().split(',')[1];},{title,color});
   const f=new FormData();f.append('front',new Blob([Buffer.from(png,'base64')],{type:'image/png'}),'cover.png');f.append('library_id',libraryId);f.append('shelf',index<3?'Shelf A':'Shelf B');
   const scan=await api('/scans',token,f);
   for(let n=0;n<100;n++){if((await api(scan.status_url,token)).status==='ready')break;await new Promise(r=>setTimeout(r,80));}
   await api(scan.status_url+'/save',token,{title,author,isbn});
  }
  await fs.mkdir('/tmp/bookbridge-cards-qa',{recursive:true});
  await page.locator('#guest-navigation [data-tab=public]').click();await page.locator('.library-card').first().waitFor();
  assert.equal(await page.locator('.library-card').count(),2);await page.screenshot({path:'/tmp/bookbridge-cards-qa/libraries.png',fullPage:true});
  await page.locator('.library-card').filter({hasText:'Town Lending Library'}).getByRole('button',{name:'View books'}).click();await page.locator('#public-results .book-card').first().waitFor();
  assert.equal(await page.locator('#public-results .book-card').count(),3);assert.equal(await page.locator('#public-filters').getAttribute('open'),null);
  const text=await page.locator('#public-results').textContent();assert(!text.includes('copies'));assert(!text.includes('ISBN'));assert(!text.includes('9780261103344'));assert(text.includes('Shelf A (1)'));
  await page.locator('#public-results .catalog-cover').first().evaluate(img=>img.complete?Promise.resolve():new Promise(resolve=>img.onload=resolve));
  await page.screenshot({path:'/tmp/bookbridge-cards-qa/books.png',fullPage:true});
  await page.getByRole('button',{name:'The Hobbit by J. R. R. Tolkien',exact:true}).click();await page.locator('#public-book-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#public-book-copies').textContent(),'2 copies');assert((await page.locator('#public-book-isbn').textContent()).includes('9780261103344'));await page.locator('[data-close=public-book-dialog]').click();
  await page.locator('#public-filters summary').click();await page.locator('#page-public [data-catalog-view=list]').click();assert.equal(await page.locator('#public-results img').count(),0);assert.equal(await page.locator('#public-results .book-cover-area').count(),0);
  assert.equal(await page.locator('#page-public [data-catalog-view=list]').getAttribute('aria-pressed'),'true');await page.locator('#public-filters summary').click();await page.screenshot({path:'/tmp/bookbridge-cards-qa/list.png',fullPage:true});
  await page.locator('#public-back').click();await page.locator('.library-card').first().waitFor();assert.equal(await page.locator('#public-results img').count(),0);
  await page.reload();await page.locator('#guest-navigation [data-tab=public]').click();await page.locator('.library-card').first().waitFor();assert.equal(await page.locator('#public-results img').count(),0);
  await page.locator('#guest-signin').click();await page.locator('#auth-name').fill('manager_ui');await page.locator('#auth-password').fill('testing123');await page.locator('#auth-submit').click();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('#workspace .navigation [data-tab=library]').click();await page.locator('#book-grid .book-card').first().waitFor();
  assert.equal(await page.locator('#book-grid img').count(),0);await page.locator('#page-library summary').click();await page.locator('#page-library [data-catalog-view=cards]').click();assert.equal(await page.locator('#book-grid .book-cover-area').count(),3);
  assert(!(await page.locator('#book-grid').textContent()).includes('copies'));assert(!(await page.locator('#book-grid').textContent()).includes('ISBN'));
  await page.getByRole('button',{name:'The Hobbit by J. R. R. Tolkien',exact:true}).click();await page.locator('#copies-dialog').waitFor({state:'visible'});assert((await page.locator('#copies-title').textContent()).includes('2 copies'));await page.locator('[data-close=copies-dialog]').click();
  for(const width of [320,390,430,600]){await page.setViewportSize({width,height:844});assert.equal(await page.locator('#book-grid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),2);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);}
  await page.locator('#page-library [data-catalog-view=list]').click();await page.getByRole('button',{name:'The Hobbit by J. R. R. Tolkien',exact:true}).click();await page.locator('#copies-dialog').waitFor({state:'visible'});await page.locator('[data-close=copies-dialog]').click();assert.deepEqual(errors,[]);
  console.log('Card/list checks passed: two columns, private/public catalogs, no list photos, saved preference, details-only ISBN/copy count, library cards, and mobile widths.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
