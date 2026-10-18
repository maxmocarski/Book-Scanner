// Use only the disposable tests/ui/mock_server.py server. Inference is mocked.
const {chromium,webkit,devices}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const base=process.argv[2] || 'http://127.0.0.1:8765';
const out=process.env.BOOKBRIDGE_UI_SCREENSHOTS || '/tmp/bookbridge-iphone-check';
async function main(){
  const engine=process.env.BOOKBRIDGE_BROWSER || 'chromium';
  const browser=await (engine==='webkit'?webkit:chromium).launch(engine==='webkit'?{headless:true}:{headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--disable-gpu']});
  try{
    const context=await browser.newContext({...devices['iPhone 13'],defaultBrowserType:undefined,...(engine==='chromium'?{permissions:['camera']}:{} )});
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    await fs.mkdir(out,{recursive:true});
    const password='testing123', name='reader_ui';
    async function req(path,token,body,method){
      const form=body instanceof FormData;
      const r=await fetch(base+path,{method:method || (body?'POST':'GET'),headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body&&!form?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});
      const result=r.status===204?null:await r.json();assert(r.ok,JSON.stringify({path,status:r.status,result}));return result;
    }
    const text=(selector,value)=>page.waitForFunction(([s,v])=>document.querySelector(s)?.textContent.includes(v),[selector,value]);
    const nav=async tab=>{if(tab==='queue'){await page.locator('#workspace .navigation [data-tab=scan]').click();await page.locator('#scan-tabs [data-tab=queue]').click();}else if(tab==='trades'){await page.locator('#workspace .navigation [data-tab=friends]').click();await page.locator('#friends-tabs [data-tab=trades]').click();}else await page.locator('#workspace .navigation [data-tab='+tab+']').click();};
    const closed=()=>page.waitForFunction(()=>![...document.querySelectorAll('.page:not([hidden]) details')].some(d=>d.open));
    const summary=(root,label)=>page.locator(root+' summary').filter({hasText:new RegExp('^'+label+'$')}).click();
    async function setup(first,last){
      await page.locator('#profile-dialog').waitFor({state:'visible'});
      await page.locator('#profile-first').fill(first);await page.locator('#profile-last').fill(last);
      await page.locator('#profile-town').fill('Fairfield, CT');
      await page.locator('#profile-form button').click();await page.locator('#profile-dialog').waitFor({state:'hidden'});
    }
    async function login(username,pw){
      if(await page.locator('#auth-submit').textContent()==='Create account')await page.locator('#auth-toggle').click();
      await page.locator('#auth-name').fill(username);await page.locator('#auth-password').fill(pw);await page.locator('#auth-submit').click();await page.locator('#workspace').waitFor({state:'visible'});
    }
    await page.goto(base);assert.equal(await page.locator('#auth-website').isVisible(),false);
    await page.locator('#auth-toggle').click();await page.locator('#auth-name').fill(name);await page.locator('#auth-password').fill(password);await page.locator('#auth-submit').click();await setup('Max','Reader');
    let token=await page.evaluate(()=>sessionStorage.getItem('bookbridge-token'));const me=await req('/me',token);
    await nav('settings');await closed();await summary('#page-settings','Your profile');assert.equal(await page.locator('#setting-name').inputValue(),'Max');assert.equal(await page.locator('#setting-lastname').inputValue(),'Reader');
    await page.locator('#setting-town').fill('New Haven, CT');await page.getByRole('button',{name:'Save profile',exact:true}).click();await text('#toast','Settings saved');
    await summary('#page-settings','Privacy');await page.locator('#setting-discovery').check();await page.getByRole('button',{name:'Save settings',exact:true}).click();await text('#toast','Settings saved');
    await nav('scan');await nav('settings');await closed();
    await page.screenshot({path:out+'/01-phone-settings.png',fullPage:true});
    await page.locator('#logout').click();await page.locator('#auth').waitFor({state:'visible'});await login(name,password);
    assert.equal(await page.locator('#profile-dialog').isVisible(),false);token=await page.evaluate(()=>sessionStorage.getItem('bookbridge-token'));
    await nav('settings');await summary('#page-settings','Your profile');assert.equal(await page.locator('#setting-town').inputValue(),'New Haven, CT');assert.equal(await page.locator('#setting-name').inputValue(),'Max');
    await nav('scan');assert.equal(await page.locator('#camera-frame').count(),0);await page.locator('#scan-shelf').fill('Living room, shelf 2');
    if(engine==='chromium'){await page.locator('#camera-open').click();await page.locator('#camera-controls').waitFor({state:'visible'});await page.locator('#camera-close').click();}
    const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=200;c.height=300;const x=c.getContext('2d');x.fillStyle='#354c3b';x.fillRect(0,0,200,300);return c.toDataURL('image/png').split(',')[1];});const buffer=Buffer.from(png,'base64');
    async function scan(t,lib){const f=new FormData();f.append('shelf',await page.locator('#scan-shelf').inputValue());f.append('front',new Blob([buffer],{type:'image/png'}),'book.png');if(lib)f.append('library_id',lib);const scan=await req('/scans',t,f);for(let i=0;i<100;i++){const r=await req(scan.status_url,t);if(r.status==='ready')return r;await new Promise(r=>setTimeout(r,100));}throw Error('Scan timed out');}
    await scan(token);await scan(token);await nav('queue');await text('#queue-list','Possible duplicate');await page.screenshot({path:out+'/02-duplicate-warning.png',fullPage:true});
    await page.locator('#bulk-review').click();await text('#queue-list','A clear queue');await nav('library');await page.waitForFunction(()=>document.querySelectorAll('#book-grid .book-spine').length===1);assert(!(await page.locator('#book-grid').textContent()).includes('2 copies'));await text('#book-grid','Living room, shelf 2');
    await page.locator('#book-grid .book-spine').click();await page.locator('#copies-dialog').waitFor({state:'visible'});await text('#copies-count','2 copies');await page.getByRole('button',{name:'Open copy 2',exact:true}).click();await page.locator('#book-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#book-shelf').inputValue(),'Living room, shelf 2');await page.locator('[data-close=book-dialog]').click();
    let books=await req('/books',token);await req('/books/'+books[0].id,token,{title:books[0].title,author:books[0].author,isbn:'9780306406157'},'PATCH');await page.locator('#library-refresh').click();await page.waitForFunction(()=>document.querySelectorAll('#book-grid .book-spine').length===2);
    const friend=await req('/auth/register',null,{username:'friend_ui',password});await req('/me/profile-setup',friend.access_token,{first_name:'Other',last_name:'Reader',town:'New Haven, CT'});await req('/me/settings',friend.access_token,{discoverable:true},'PATCH');const fscan=await scan(friend.access_token);await req(fscan.status_url+'/save',friend.access_token,{title:'Only in friend library',author:'Friend Author',available:true});
    await nav('friends');await closed();const headings=await page.locator('#page-friends summary').allTextContents();assert.equal(headings[0],'Quick add friends');await summary('#page-friends','Quick add friends');await text('#suggestions','Other Reader');await page.locator('#suggestions').getByRole('button',{name:'Add friend'}).click();await text('#toast','Friend request sent');await req('/people/'+me.id+'/accept',friend.access_token,{});await page.locator('#friends-refresh').click();await text('#friend-list','Other Reader');await page.locator('#friend-list').getByRole('button',{name:'Browse books'}).click();await text('#book-grid','Only in friend library');assert(!(await page.locator('#book-grid').textContent()).includes('The Great Gatsby'));await page.locator('#my-library').click();await text('#book-grid','The Great Gatsby');assert(!(await page.locator('#book-grid').textContent()).includes('Only in friend library'));
    const manager=await req('/auth/register',null,{username:'manager_ui',password});
    await nav('settings');await page.locator('#logout').click();await login('manager_ui',password);await setup('Library','Manager');
    await nav('settings');await closed();await page.locator('#admin-open').click();await closed();await summary('#page-admin','Create a shared library');await page.locator('#new-library-name').fill('School Library');await page.getByRole('button',{name:'Create library',exact:true}).click();await text('#shared-libraries','School Library');
    await summary('#page-settings','Shared libraries');await page.locator('#shared-libraries summary').filter({hasText:'School Library'}).click();const card=page.locator('.library-settings').filter({hasText:'School Library'});await card.getByRole('textbox').fill(name);await card.getByRole('button',{name:'Add member',exact:true}).click();await text('#shared-libraries','Max Reader');
    token=(await req('/auth/login',null,{username:name,password})).access_token;const lib=(await req('/libraries',manager.access_token))[0];await scan(token,lib.id);await req('/libraries/'+lib.id+'/accept-ready',manager.access_token,{acknowledge:true});await scan(token,lib.id);
    await page.locator('#admin-open').click();await closed();await summary('#page-admin','Manage shared libraries');await text('#admin-libraries','School Library');await page.locator('#admin-libraries summary').filter({hasText:'School Library'}).click();await page.locator('#admin-libraries').getByRole('button',{name:'Delete library',exact:true}).click();await page.locator('#delete-library-name').fill('School Library');await page.getByRole('button',{name:'Permanently delete library',exact:true}).click();await page.locator('#delete-library-dialog').waitFor({state:'hidden'});assert.deepEqual(await req('/libraries',manager.access_token),[]);
    await summary('#page-admin','Accounts');await page.locator('#admin-user-query').fill(name);await page.locator('#admin-user-search button').click();await text('#admin-users',name);await page.locator('#admin-users').getByRole('button',{name:'Reset password',exact:true}).click();await page.locator('#reset-code-dialog').waitFor({state:'visible'});const reset=await page.locator('#admin-reset-code').inputValue();assert(reset.length>20);await page.locator('[data-close=reset-code-dialog]').click();await page.waitForFunction(()=>document.querySelector('#admin-reset-code').value==='');
    await page.screenshot({path:out+'/03-phone-admin.png',fullPage:true});
    await nav('settings');await page.locator('#logout').click();await page.locator('#forgot-password').click();await page.locator('#recovery-username').fill(name);await page.locator('#recovery-code').fill(reset);await page.locator('#recovery-password').fill('new-password-123');await page.locator('#recovery-confirm').fill('new-password-123');await page.locator('#recovery-finish button').click();await page.locator('#recovery-dialog').waitFor({state:'hidden'});await login(name,'new-password-123');await text('#username','Max Reader');
    for(const [width,height] of [[320,568],[390,844],[430,932],[844,390],[1280,900]]){
      await page.setViewportSize({width,height});await nav('settings');await closed();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Horizontal overflow at '+width);
      assert(await page.evaluate(()=>Math.abs(document.querySelector('#workspace .navigation').getBoundingClientRect().bottom-window.innerHeight)<2),'Bottom navigation at '+width);
    }
    assert.deepEqual(errors,[]);console.log(engine+': profile persistence, closed sections, duplicates, edition grouping, friend navigation, shared membership/deletion, password reset, and mobile layouts passed.');
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
