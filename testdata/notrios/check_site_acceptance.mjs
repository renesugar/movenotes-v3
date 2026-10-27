// Development-only live acceptance; requires an existing Playwright installation.
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [workDir, playwrightModule] = process.argv.slice(2);
if (!workDir || !playwrightModule) throw new Error('Usage: node check_site_acceptance.mjs WORK_DIR PLAYWRIGHT_MODULE');
const {chromium} = await import(pathToFileURL(path.resolve(playwrightModule)).href);
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const expected=JSON.parse(await fs.readFile(new URL('./schema28/publication-loose/expected.json', import.meta.url),'utf8'));
const browser=await chromium.launch({headless:true}); const report={};
try {
for (const [backend,port] of [['bluge',18771],['pagefind',18772]]) {
 const origin=`http://127.0.0.1:${port}`, base=origin+'/archive/';
 const page=await browser.newPage({viewport:{width:1365,height:900}}), errors=[],failed=[],requests=[];
 page.on('pageerror',e=>errors.push(String(e))); page.on('console',m=>{if(m.type()==='error') errors.push(m.text())});
 page.on('response',r=>{if(r.status()>=400) failed.push([r.status(),r.url()])});
 page.on('request',r=>requests.push(r.url()));
 const rows=(await fs.readFile(`${workDir}/${backend}/server/search-source.jsonl`,'utf8')).trim().split('\n').map(JSON.parse);
 const urls=rows.map(r=>decodeURI('/archive'+r.url)).sort();
 await page.goto(base+'notes/public/cafe-field-notes.html');
 assert.match(await page.title(),/Café/); assert.match(await page.locator('main').innerText(),/Préface café/);
 assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),base+'notes/public/cafe-field-notes.html');
 const child=page.getByRole('link',{name:'child section',exact:true}); await child.click();
 assert.equal(decodeURI(page.url()),base+'notes/public/研究/child-東京.html#details');
 await page.getByRole('link',{name:'Back',exact:true}).click();
 assert.equal(page.url(),base+'notes/public/cafe-field-notes.html');
 const images=await page.locator('main img').evaluateAll(xs=>xs.map(x=>({src:x.src,ok:x.complete&&x.naturalWidth>0})));
 assert.ok(images.length); assert.ok(images.every(x=>x.ok&&x.src.startsWith(base)));
 for(const [label,key] of [['field notes','res_text'],['related.bin','res_sidecar']]){
   const href=await page.getByRole('link',{name:label,exact:true}).getAttribute('href');
   const url=new URL(href,page.url()).href; assert.ok(url.startsWith(base));
   const response=await page.request.get(url); assert.equal(response.status(),200);
   assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex'),expected.resources[key].sha256);
 }
 await page.goto(base+'search/'); assert.match(await page.title(),/Search/);
 const counts={};
 for(const [tag,count,slug] of [['published',3,'published'],['café',1,'café'],['research notes',1,'research-notes'],['東京',1,'東京']]){
   const query=tag.includes(' ')?`tag:"${tag}"`:`tag:${tag}`;
   await page.locator('[data-ledger-search-input]').fill(query); await page.locator('[data-ledger-search-input]').press('Enter');
   await page.waitForFunction(n=>document.querySelectorAll('[data-ledger-search-results] a.ledger-card').length===n,count);
   const links=await page.locator('[data-ledger-search-results] a.ledger-card').evaluateAll(xs=>xs.map(x=>decodeURI(x.getAttribute('href'))).sort());
   assert.deepEqual(links,rows.filter(r=>r.tags.includes(tag)).map(r=>decodeURI('/archive'+r.url)).sort());
   counts[tag]=links.length;
   const tax=await page.request.get(base+'tags/'+encodeURIComponent(slug)+'/'); assert.equal(tax.status(),200);
   // Taxonomy pages render note cards without invoking a browser backend.
   const tagPage=await browser.newPage(); await tagPage.goto(base+'tags/'+encodeURIComponent(slug)+'/');
   assert.equal(await tagPage.locator('a.ledger-card').count(),count); await tagPage.close();
 }
 await page.locator('[data-ledger-search-input]').fill('tag:published');await page.locator('[data-ledger-search-input]').press('Enter');
 await page.waitForFunction(()=>document.querySelectorAll('[data-ledger-search-results] a.ledger-card').length===3);
 await page.screenshot({path:`${workDir}/${backend}-desktop.png`});
 await page.setViewportSize({width:390,height:844}); await page.screenshot({path:`${workDir}/${backend}-mobile.png`});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 for(const sentinel of [...expected.forbidden_in_archive,expected.commit_sha256,expected.selection_manifest_sha256]) {
   const query='"'+sentinel+'"';
   await page.locator('[data-ledger-search-input]').fill(query);
   await page.locator('[data-ledger-search-input]').press('Enter');
   await page.waitForFunction(q=>{
     const meta=document.querySelector('[data-ledger-result-count]');
     return meta?.textContent.includes(q)&&document.querySelectorAll('[data-ledger-search-results] a.ledger-card').length===0;
   },query);
 }
 const receipt=await page.request.get(base+'movenotes/notrios-receipt.json');assert.equal(receipt.status(),200);
 assert.equal((await receipt.json()).commit_sha256,expected.commit_sha256);
 if(backend==='bluge'){assert.ok(requests.some(u=>u.includes('/api/search')));assert.ok(!requests.some(u=>u.includes('/pagefind/')));}
 else {assert.ok(requests.some(u=>u.includes('/pagefind/')));assert.ok(!requests.some(u=>u.includes('/api/')));}
 assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
 report[backend]={counts,urls,images,excludedSearches:expected.forbidden_in_archive.length+2,consoleErrors:errors,httpFailures:failed,requests:requests.filter(u=>/api\/|pagefind\//.test(u)),screenshots:[`${backend}-desktop.png`,`${backend}-mobile.png`]};
 await page.close();
}
await fs.writeFile(path.join(workDir, 'browser-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
} finally {await browser.close();}
