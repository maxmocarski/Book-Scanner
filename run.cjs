// Run only against tests/ui/mock_server.py: creates disposable users, books, and libraries.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const out = process.env.BOOKBRIDGE_UI_SCREENSHOTS || '/tmp/bookbridge-ui-check';
async function main() {
  const browser = await chromium.launch({headless:true,executablePath:process.env.BOOKBRIDGE_CHROMIUM || undefined,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--disable-gpu']});
  try {
    const context=await browser.newContext({viewport:{width:1280,height:900},permissions:['camera']});
    const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    page.on('dialog',dialog=>dialog.accept());
    await fs.mkdir(out,{recursive:true});
    const password='testpass8', name='reader_ui', friendName='friend_ui';
    async function req(path,token,body,method) {
      const multipart=body instanceof FormData;
      const response=await fetch(base+path,{method:method || (body?'POST':'GET'),headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body&&!multipart?{'Content-Type':'application/json'}:{})},body:body?(multipart?body:JSON.stringify(body)):undefined});
      const result=response.status===204?null:await response.json();assert(response.ok,JSON.stringify({path,status:response.status,result}));return result;
    }
    const text=async(selector,value)=>page.waitForFunction(([s,v])=>document.querySelector(s)?.textContent.includes(v),[selector,value],{timeout:15000});
    const visible=async s=>page.locator(s).waitFor({state:'visible'});
    await page.goto(base);await page.locator('#auth-toggle').click();await page.locator('#auth-name').fill(name);await page.locator('#auth-password').fill(password);await page.locator('#auth-submit').click();await visible('#workspace');
    const token=await page.evaluate(()=>sessionStorage.getItem('bookbridge-token'));
    const me=await req('/me',token);
    await page.locator('[data-tab=settings]').click();await page.locator('#setting-name').fill('Max Reader');await page.locator('#setting-town').fill('Fairfield, CT');await page.locator('#setting-discovery').check();await page.locator('#scan-mode').selectOption('lookup');await page.locator('#settings-form').getByRole('button',{name:'Save settings',exact:true}).click();await text('#username','Max Reader');
    await page.locator('[data-tab=scan]').click();await page.locator('#camera-open').click();await visible('#camera-controls');await page.locator('#shutter').click();await page.waitForFunction(()=>document.querySelectorAll('.photo-choice img').length===1);await page.locator('#camera-close').click();
    const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=200;c.height=300;const x=c.getContext('2d');x.fillStyle='#283d32';x.fillRect(0,0,200,300);return c.toDataURL('image/png').split(',')[1];});
    const buffer=Buffer.from(png,'base64');
    // Upload a second and third angle through the real photo controls.
    for(const view of ['spine','back']) {
      await page.locator('#photo-input').evaluate((input,v)=>{input.dataset.view=v;},view);
      await page.locator('#photo-input').setInputFiles({name:view+'.png',mimeType:'image/png',buffer});
      await page.waitForFunction(n=>document.querySelectorAll('.photo-choice img').length===n,view==='spine'?2:3);
    }
    await page.locator('#queue-book').click();await text('#scan-feedback','Book queued');await page.locator('[data-tab=queue]').click();await page.getByRole('button',{name:'Review',exact:true}).click();await visible('#review-dialog');assert.equal(await page.locator('#review-photos figure').count(),3);assert.equal(await page.locator('#review-book-title').inputValue(),'The Great Gatsby');await page.locator('#review-available').check();await page.getByRole('button',{name:'Save to my library',exact:true}).click();await page.locator('#review-dialog').waitFor({state:'hidden'});
    await page.locator('[data-tab=library]').click();await visible('.book-card');await page.locator('.book-card').first().click();await page.locator('#reading-open').click();await visible('#reading-dialog');await page.locator('#reading-pages').fill('123');await page.locator('#reading-review').fill('A thoughtful story.');await page.locator('#reading-rating').selectOption('4');await page.getByRole('button',{name:'Save reading log',exact:true}).click();await page.locator('#reading-dialog').waitFor({state:'hidden'});
    await page.locator('[data-tab=settings]').click();await page.locator('[data-tab=stats]').click();await text('#reading-stats','123');await page.screenshot({path:out+'/reading-stats.png',fullPage:true});
    const friend=await req('/auth/register',null,{username:friendName,password});
    await req('/me/settings',friend.access_token,{display_name:'Other Reader',town:'Fairfield, CT',discoverable:true},'PATCH');
    await page.locator('[data-tab=friends]').click();await text('#suggestions','Other Reader');await page.locator('#suggestions').getByRole('button',{name:'Add friend'}).click();await text('#friend-requests','request sent');await req('/people/'+me.id+'/accept',friend.access_token,{},'POST');await page.locator('#friends-refresh').click();await text('#friend-list','Other Reader');
    async function scanFor(token,library) {
      const form=new FormData();form.append('front',new Blob([buffer],{type:'image/png'}),'book.png');if(library)form.append('library_id',library);
      const scan=await req('/scans',token,form);let ready;
      for(let n=0;n<100;n++){ready=await req(scan.status_url,token);if(ready.status==='ready')return ready;await new Promise(r=>setTimeout(r,100));}
      throw Error('Scan did not finish');
    }
    const friendScan=await scanFor(friend.access_token);await req(friendScan.status_url+'/save',friend.access_token,{title:'Friend book',author:'An Author',available:true});
    await page.locator('#friend-list').getByRole('button',{name:'Browse books'}).click();await text('#book-grid','Friend book');await page.locator('.book-card').first().click();await page.locator('#request-swap').click();await visible('#swap-dialog');await page.locator('#swap-offer').selectOption({index:1});await page.locator('#swap-submit').click();await text('#trade-list','Your request');const trade=(await req('/trades',token))[0];await req('/trades/'+trade.id+'/accept',friend.access_token,{});await page.locator('[data-tab=trades]').click();await page.getByRole('button',{name:'Confirm handoff'}).click();await req('/trades/'+trade.id+'/confirm-handoff',friend.access_token,{});
    await scanFor(token);await page.locator('[data-tab=queue]').click();await text('#queue-list','READY TO REVIEW');await page.locator('#bulk-review').click();await text('#queue-list','A clear queue');
    const manager=await req('/auth/register',null,{username:'manager_ui',password});
    const library=await req('/libraries',manager.access_token,{name:'School library'});await req('/libraries/'+library.id+'/members',manager.access_token,{username:name});
    await page.locator('[data-tab=settings]').click();await text('#shared-libraries','School library');await page.locator('#shared-libraries summary').click();await page.getByRole('button',{name:'Scan into library',exact:true}).click();assert.equal(await page.locator('#scan-library').inputValue(),library.id);
    await page.locator('#photo-input').evaluate(input=>{input.dataset.view='front';});await page.locator('#photo-input').setInputFiles({name:'cover.png',mimeType:'image/png',buffer});await page.locator('#queue-book').click();await text('#scan-feedback','Book queued');await page.locator('[data-tab=queue]').click();await page.locator('#queue-library').selectOption(library.id);await text('#queue-list','READY TO REVIEW');await page.locator('#bulk-review').click();await text('#queue-list','A clear queue');
    await page.locator('[data-tab=library]').click();await page.locator('.filters summary').click();await page.locator('#library-owner').selectOption('lib:'+library.id);await text('#library-title','School library');await visible('.book-card');
    await req('/libraries/'+library.id+'/members/'+me.id,manager.access_token,null,'DELETE');await page.locator('#library-refresh').click();await text('#library-title','Your little library');
    await page.setViewportSize({width:390,height:844});await page.locator('[data-tab=settings]').click();await page.screenshot({path:out+'/phone-settings.png',fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile horizontal overflow');
    assert(await page.evaluate(()=>Math.abs(document.querySelector('.navigation').getBoundingClientRect().bottom-window.innerHeight)<2),'Navigation is not at bottom');
    await page.locator('#logout').click();await visible('#auth');await page.locator('#auth-toggle').click(); // return from registration to sign in
    await page.locator('#auth-name').fill('manager_ui');await page.locator('#auth-password').fill(password);await page.locator('#auth-submit').click();await visible('#workspace');await page.locator('[data-tab=settings]').click();await page.locator('#admin-open').click();await text('#admin-stats','Accounts');
    await page.locator('#new-library-name').fill('Town library');await page.getByRole('button',{name:'Create library',exact:true}).click();await text('#shared-libraries','Town library');await page.locator('#shared-libraries summary').filter({hasText:'Town library'}).click();const card=page.locator('.library-settings').filter({hasText:'Town library'});await card.locator('input').fill(name);await card.getByRole('button',{name:'Add member',exact:true}).click();await text('#shared-libraries','Max Reader');
    await page.locator('#admin-open').click();await page.locator('#admin-user-query').fill(friendName);await page.locator('#admin-user-search button').click();await text('#admin-users',friendName);await page.locator('#admin-users').getByRole('button',{name:'Ban',exact:true}).click();await text('#admin-users','banned');await page.screenshot({path:out+'/phone-admin.png',fullPage:true});
    assert.deepEqual(errors,[]);console.log('Browser flows passed: scan/review, settings, reading, discovery, swaps, bulk save, shared library/revocation, admin, and mobile navigation.');
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
