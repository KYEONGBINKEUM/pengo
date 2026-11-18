import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops, ImageStat
base=Path(__file__).resolve().parents[1];qa=base/'verification'
with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    rows=[]
    for w in [1920,390]:
        p=b.new_page(viewport={'width':w,'height':1000})
        p.goto((base/'automatic-sample/preview.html').as_uri(),wait_until='load')
        p.wait_for_function('Array.from(document.images).every(x=>x.complete)')
        rows.append({'width':w,'dom_texts':p.locator('[data-layer]').count(),'horizontal_overflow':p.evaluate('document.documentElement.scrollWidth>innerWidth'),
                    'broken_images':p.locator('img').evaluate_all('(xs)=>xs.filter(x=>x.naturalWidth===0).length')})
        if w==1920:p.locator('.draft-canvas').screenshot(path=str(qa/'automatic-desktop.png'))
        p.close()
    b.close()
original=Image.open(base/'automatic-sample/analysis/reference.png').convert('RGB');generated=Image.open(qa/'automatic-desktop.png').convert('RGB')
if original.size==generated.size:
    diff=ImageChops.difference(original,generated)
    mean=sum(ImageStat.Stat(diff).mean)/3
    diff.save(qa/'automatic-difference.png')
else:mean=None
report={'browser':rows,'desktop_rgb_mean_absolute_error_0_to_255':mean,'metric_note':'픽셀 평균 절대차. 글꼴 대체와 합성/배치 차이 포함. 정확도 백분율이나 합격 기준으로 사용하지 않음.'}
(qa/'automatic-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
thumb=generated.copy();thumb.thumbnail((960,4000));thumb.save(qa/'automatic-preview.jpg')
print(json.dumps(report,ensure_ascii=False,indent=2))
assert all(r['dom_texts']==98 and not r['horizontal_overflow'] and not r['broken_images'] for r in rows)
