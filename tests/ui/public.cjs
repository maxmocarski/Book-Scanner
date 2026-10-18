// Run only against the disposable tests/ui/mock_server.py server.
const {chromium,devices}=require('playwright');
const assert=require('node:assert/strict');
const base=process.argv[2] || 'http://127.0.0.1:8765';
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--use-gl=angle','--use-angle=swiftshader']});
  try{
    const context=await browser.newContext({...devices['iPhone 13']});
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    async function api(path,token,body,method){const form=body instanceof FormData;const r=await fetch(base+path,{method:method || (body?'POST':'GET'),headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body&&!form?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});const data=await r.json();assert(r.ok,JSON.stringify(data));return data;}
    const manager=await api('/auth/register',null,{username:'manager_ui',password:'testing123'});const token=manager.access_token;
    await api('/me/profile-setup',token,{first_name:'Library',last_name:'Manager'});
    const lib=await api('/libraries',token,{name:'Public Town Library',is_public:true});
    await api('/libraries',token,{name:'Secret library'});
    // Generate a valid PNG in the browser before submitting mocked-inference scan.
    await page.goto(base);
    const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=100;c.height=150;c.getContext('2d').fillRect(0,0,100,150);return c.toDataURL().split(',')[1];});
    const form=new FormData();form.append('front',new Blob([Buffer.from(png,'base64')],{type:'image/png'}),'cover.png');form.append('library_id',lib.id);form.append('shelf','Shelf A');
    const scan=await api('/scans',token,form);
    for(let n=0;n<100;n++){const data=await api(scan.status_url,token);if(data.status==='ready')break;await new Promise(r=>setTimeout(r,100));}
    await api(scan.status_url+'/save',token,{title:'Public Book','author':'Book Author'});
    await page.locator('#guest-navigation [data-tab=public]').click();
    await page.getByRole('button',{name:'View books'}).waitFor();assert(!(await page.locator('#public-results').textContent()).includes('Secret library'));
    assert.equal(await page.locator('#auth').isVisible(),false);assert.equal(await page.locator('#workspace').isVisible(),false);
    await page.getByRole('button',{name:'View books'}).click();await page.getByRole('button',{name:'Public Book by Book Author'}).click();
    await page.locator('#public-book-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#public-book-shelf').textContent(),'Shelf: Shelf A (1)');
    await page.locator('#public-book-photos img').first().evaluate(img=>img.complete?Promise.resolve():new Promise(resolve=>img.onload=resolve));
    assert(await page.locator('#public-book-photos img').first().evaluate(img=>img.naturalWidth>0));
    assert.equal(await page.locator('#public-book-dialog input').count(),0);
    await page.locator('[data-close=public-book-dialog]').click();
    await api('/libraries/'+lib.id+'/visibility',token,{is_public:false},'PATCH');await page.locator('#public-filters summary').click();await page.locator('#public-search-form button').click();
    await page.waitForFunction(()=>document.querySelector('#public-status').textContent.includes('not found'));assert.equal(await page.locator('#public-results .book-spine').count(),0);
    await page.locator('#guest-signin').click();await page.locator('#auth-name').fill('manager_ui');await page.locator('#auth-password').fill('testing123');await page.locator('#auth-submit').click();await page.locator('#workspace').waitFor({state:'visible'});
    assert.equal(await page.locator('#guest-navigation').isVisible(),false);
    await page.locator('#workspace .navigation [data-tab=settings]').click();await page.locator('#page-settings summary').filter({hasText:/^Shared libraries$/}).click();
    await page.locator('#shared-libraries summary').filter({hasText:'Public Town Library'}).click();
    const card=page.locator('#shared-libraries .library-settings').filter({hasText:'Public Town Library'});await card.getByRole('switch',{name:'Public library',exact:true}).check();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Library is public.');
    await page.locator('#library-owner').selectOption('__public__');await page.getByRole('button',{name:'Public Book by Book Author'}).waitFor();
    for(const width of [320,390,430]){await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);}
    await page.screenshot({path:'/tmp/bookbridge-public-phone.png',fullPage:true});
    assert.deepEqual(errors,[]);console.log('Public iPhone-size flow passed: anonymous browsing/photos, privacy revocation, sign-in, manager toggle, and mobile widths.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
