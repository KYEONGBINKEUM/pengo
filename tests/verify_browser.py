import json, subprocess, time, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
base=Path(__file__).resolve().parents[1]; sample=base/'sample'; qa=base/'verification';qa.mkdir(exist_ok=True)
results={'php_lint':[],'browser':[]}
for f in sample.rglob('*.php'):
    r=subprocess.run(['php','-l',str(f)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    results['php_lint'].append({'file':str(f.relative_to(sample)),'pass':r.returncode==0,'output':r.stdout.strip()})
p=subprocess.Popen(['php','-S','127.0.0.1:18765','-t',str(sample)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    time.sleep(1)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        for width in [1920,768,390]:
            page=browser.new_page(viewport={'width':width,'height':1000},device_scale_factor=1)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            response=page.goto('http://127.0.0.1:18765/index.php',wait_until='networkidle')
            page.locator('img').evaluate_all('(xs)=>xs.forEach(x=>x.loading="eager")')
            page.wait_for_function('Array.from(document.images).every(x=>x.complete)')
            page.screenshot(path=str(qa/f'sample-{width}.png'),full_page=True)
            row={'width':width,'status':response.status,'js_errors':errors,
                 'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth > innerWidth'),
                 'broken_images':page.locator('img').evaluate_all('(xs)=>xs.filter(x=>!x.complete||x.naturalWidth===0).map(x=>x.src)'),
                 'course_count':page.locator('.course-card:visible').count()}
            page.get_by_role('button',name='대중소상생 공동훈련센터',exact=True).click()
            row['filter_count']=page.locator('.course-card:visible').count()
            page.get_by_role('button',name='전체',exact=True).click()
            row['reset_count']=page.locator('.course-card:visible').count()
            question=page.locator('.faq-list details').nth(1);question.locator('summary').click(); row['faq_open']=question.get_attribute('open') is not None
            if width<=1024:
                page.get_by_role('button',name='메뉴',exact=True).click();row['menu_open']=page.locator('#site-nav').is_visible()
                page.locator('#site-nav a').nth(2).click();row['menu_closed_after_link']=not page.locator('#site-nav').is_visible()
            results['browser'].append(row);page.close()
        browser.close()
finally:p.terminate();p.wait()
(qa/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(results,ensure_ascii=False,indent=2))
assert all(x['pass'] for x in results['php_lint'])
assert all(x['status']==200 and not x['js_errors'] and not x['horizontal_overflow'] and not x['broken_images'] and x['filter_count']==2 and x['reset_count']==5 and x['faq_open'] for x in results['browser'])
