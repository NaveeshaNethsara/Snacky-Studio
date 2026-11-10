import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('two prepared files hand off to the native download manager after a refresh',async({page,request})=>{
 await page.goto('/');
 await page.getByLabel('Video or photo-post link').fill('https://example.com/hold/first');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Download',exact:true}).click();
 await expect(page.getByLabel('Video or photo-post link')).toHaveValue('');
 await page.getByLabel('Video or photo-post link').fill('https://example.com/hold/second');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Audio · MP3',exact:true}).click();
 await page.getByRole('button',{name:'Download',exact:true}).click();
 await expect(page.getByText('2 active',{exact:true})).toBeVisible();
 await page.reload();
 await expect(page.getByText('2 active',{exact:true})).toBeVisible();
 const snapshots=(await (await request.get('/api/tasks')).json()).tasks;
 const files:import('@playwright/test').Download[]=[];
 page.on('download',download=>files.push(download));
 await request.post('/qa/release');
 await expect.poll(()=>files.length,{timeout:45000}).toBe(2);
 for(const download of files){
  expect(await download.failure()).toBeNull();
  const path=await download.path(); expect(path).toBeTruthy();
  const task=snapshots.find((task:{id:string})=>download.suggestedFilename().includes(task.id));expect(task).toBeTruthy();
  const response=await request.get(`/api/browser-download/${task.id}`);
  expect(response.status()).toBe(200);
  expect(Number(response.headers()['content-length'])).toBeGreaterThan(10000);
  expect(await readFile(path!)).toEqual(await response.body());
  expect(download.suggestedFilename()).toContain('සිංහල');
 }
 await expect(page.getByRole('button',{name:'Continue',exact:true})).toBeEnabled();
 await page.screenshot({path:'../scratch/react-downloads-verified.png',fullPage:true});
});

test('Facebook photo controls, failed retry and mobile layout remain usable',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');
 await page.getByLabel('Video or photo-post link').fill('https://example.com/failure');await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('button',{name:'Download',exact:true}).click();
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
 await page.getByLabel('Video or photo-post link').fill('https://www.facebook.com/photo?fbid=123');await page.getByRole('button',{name:'Get photo',exact:true}).click();
 await expect(page.getByRole('button',{name:'Save PNG',exact:true})).toBeVisible();
 await page.screenshot({path:'../scratch/react-mobile-verified.png',fullPage:true});
 const overflow = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('body *')]
   .filter(element => {const box=element.getBoundingClientRect();return box.width > 0 && (box.right > innerWidth+1 || box.left < -1) && getComputedStyle(element).position !== 'fixed';})
   .map(element => ({tag:element.tagName,class:element.className,right:element.getBoundingClientRect().right,left:element.getBoundingClientRect().left})));
 expect(overflow).toEqual([]);
});

test('private workspace login shows errors and returns to login after sign out',async({page})=>{
 await page.route('**/api/session',route=>route.fulfill({json:{mode:'cloud',authenticated:false}}));
 await page.route('**/api/session/login',route=>{
  const valid=route.request().postDataJSON().password==='fixture-private-password';
  return route.fulfill({status:valid ? 200 : 401,json:valid ? {mode:'cloud',authenticated:true} : {detail:'The workspace password is incorrect.'}});
 });
 await page.route('**/api/session/logout',route=>route.fulfill({json:{authenticated:false}}));
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'Your private studio',exact:true})).toBeVisible();
 await expect(page.getByLabel('Video or photo-post link')).toHaveCount(0);
 await page.getByLabel('Workspace password').fill('wrong-password');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('password is incorrect');
 await page.getByLabel('Workspace password').fill('fixture-private-password');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByLabel('Video or photo-post link')).toBeVisible();
 await page.getByRole('button',{name:'Sign out',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your private studio',exact:true})).toBeVisible();
 await expect(page.getByLabel('Video or photo-post link')).toHaveCount(0);
 await page.screenshot({path:'../scratch/react-private-login-verified.png',fullPage:true});
});
