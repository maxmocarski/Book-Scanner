// Only run against the disposable mock_server.py server; inference is mocked.
const {chromium,devices}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const base=process.argv[2] || 'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--use-gl=angle','--use-angle=swiftshader']});
 try{
  const context=await browser.newContext({...devices['iPhone 13']});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  async function api(path,token,body){const form=body instanceof FormData;const r=await fetch(base+path,{method:body?'POST':'GET',headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body&&!form?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});const data=await r.json();assert(r.ok,JSON.stringify(data));return data;}
  const manager=await api('/auth/register',null,{username:'manager_ui',password:'testing123'});const token=manager.access_token;await api('/me/profile-setup',token,{first_name:'Max',last_name:'Reader'});
  const lib=await api('/libraries',token,{name:'Town Library',is_public:true});
  await page.goto(base);
  const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=450;c.height=300;const x=c.getContext('2d');['#34523b','#6b4c3b','#4c5c60'].forEach((color,i)=>{x.fillStyle=color;x.fillRect(i*150,0,150,300);x.fillStyle='#fff9e5';x.font='20px serif';x.fillText('Book '+(i+1),i*150+30,140);});return c.toDataURL().split(',')[1];}),'base64');
  async function add(title,shelf='',isbn=null,library=''){
   const f=new FormData();f.append('front',new Blob([png],{type:'image/png'}),'book.png');f.append('shelf',shelf);if(library)f.append('library_id',library);
   const scan=await api('/scans',token,f);
   for(let i=0;i<100;i++){if((await api(scan.status_url,token)).status==='ready')break;await new Promise(r=>setTimeout(r,80));}
   await api(scan.status_url+'/save',token,{title,author:'Test Author',isbn});
  }
  await add('The Hobbit','Shelf A','9780261103344');await add('A Walk in the Woods','Shelf A');await add('The Hobbit','Shelf B','9780261103344');await add('Z first miscellaneous');await add('A second miscellaneous');
  await add('Shared Book','Shelf 1',null,lib.id);
  await page.locator('#auth-name').fill('manager_ui');await page.locator('#auth-password').fill('testing123');await page.locator('#auth-submit').click();await page.locator('#page-library').waitFor({state:'visible'});
  await page.locator('#book-grid .book-spine').first().waitFor();
  assert.deepEqual(await page.locator('#workspace > .navigation button').allTextContents(),['My Library','Scan','Friends','Settings']);
  assert.equal(await page.locator('#book-grid .book-spine').count(),4);assert.equal(await page.locator('#book-grid img').count(),0);
  assert.deepEqual(await page.locator('#book-grid .shelf-heading').allTextContents(),['Shelf A','Miscellaneous']);
  assert.deepEqual(await page.locator('#book-grid .shelf-section').last().locator('.spine-title').allTextContents(),['Z first miscellaneous','A second miscellaneous']);
  assert.deepEqual(await page.locator('#book-grid .shelf-section').first().locator('.spine-number').allTextContents(),['1','2']);
  await fs.mkdir('/tmp/bookbridge-bookshelf-qa',{recursive:true});await page.screenshot({path:'/tmp/bookbridge-bookshelf-qa/home.png',fullPage:true});
  await page.getByRole('button',{name:'The Hobbit by Test Author',exact:true}).click();await page.locator('#copies-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#copies-count').textContent(),'2 copies');assert.equal(await page.locator('#copies-photos img').count(),1);await page.locator('[data-close=copies-dialog]').click();
  await page.locator('#page-library summary').click();await page.locator('#page-library [data-catalog-view=list]').click();assert.equal(await page.locator('#book-grid img').count(),0);assert.equal(await page.locator('#book-grid .book-card').count(),4);await page.locator('#page-library [data-catalog-view=cards]').click();
  await page.locator('#library-owner').selectOption('lib:'+lib.id);await page.getByRole('button',{name:'Shared Book by Test Author',exact:true}).waitFor();
  await page.locator('#workspace .navigation [data-tab=scan]').click();assert.equal(await page.locator('#scan-library').inputValue(),lib.id);
  await page.locator('#scan-mode-kind').selectOption('shelf');assert.equal(await page.locator('#photo-slots .photo-slot').count(),1);assert(await page.locator('#scan-limit').isVisible());
  await page.locator('#shelf-book-count').selectOption('3');await page.locator('#scan-shelf').fill('Shelf 1');await page.locator('#photo-input').setInputFiles({name:'shelf.png',mimeType:'image/png',buffer:png});await page.locator('#queue-book').click();
  await page.locator('#scan-tabs [data-tab=queue]').click();await page.waitForFunction(()=>document.querySelectorAll('#queue-list .queue-card .ready').length>=3);
  await page.screenshot({path:'/tmp/bookbridge-bookshelf-qa/queue.png',fullPage:true});
  for(let i=0;i<3;i++){
   await page.locator('#queue-list').getByRole('button',{name:'Review',exact:true}).first().click();await page.locator('#review-dialog').waitFor({state:'visible'});assert((await page.locator('#review-book-title').inputValue()).startsWith('Shelf Book'));
   await page.locator('#review-form button.primary').click();await page.waitForFunction(()=>!document.querySelector('#review-dialog').open || document.querySelector('#review-error').textContent || document.querySelector('#review-form :invalid'));assert.equal(await page.locator('#review-error').textContent(),'');assert.equal(await page.locator('#review-form :invalid').count(),0);await page.locator('#review-dialog').waitFor({state:'hidden'});await page.waitForFunction(n=>document.querySelectorAll('#queue-list .queue-card').length===n,2-i);
  }
  await page.locator('#workspace .navigation [data-tab=library]').click();await page.waitForFunction(()=>document.querySelectorAll('#book-grid .book-spine').length===4);
  assert.deepEqual(await page.locator('#book-grid .spine-number').allTextContents(),['1','2','3','4']);
  await page.screenshot({path:'/tmp/bookbridge-bookshelf-qa/shared.png',fullPage:true});
  for(const width of [320,390,430,844]){
   await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page overflow at '+width);
   assert(await page.evaluate(()=>document.querySelector('#library-dock').getBoundingClientRect().bottom<=document.querySelector('#workspace > .navigation').getBoundingClientRect().top+1),'Selector above navigation at '+width);
  }
  await page.locator('#workspace .navigation [data-tab=friends]').click();await page.locator('#friends-tabs [data-tab=trades]').click();await page.locator('#page-trades').waitFor({state:'visible'});
  await page.locator('#library-owner').selectOption('__public__');await page.getByRole('button',{name:'View books'}).click();await page.locator('#public-results .book-spine').first().waitFor();
  await page.locator('#workspace .navigation [data-tab=settings]').click();await page.locator('#logout').click();await page.locator('#guest-navigation [data-tab=public]').click();await page.getByRole('button',{name:'View books'}).click();await page.locator('#public-results .book-spine').first().waitFor();
  assert.equal(await page.locator('#workspace').isVisible(),false);await page.getByRole('button',{name:'Shared Book by Test Author',exact:true}).click();await page.locator('#public-book-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#public-book-photos img').count(),1);
  assert.deepEqual(errors,[]);console.log('Bookshelf checks passed: home, four tabs, selector, grouped spines/photos/count, ordered shelves and Miscellaneous, list mode, 3-spine scan/review, shared and guest catalogs, mobile widths.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
