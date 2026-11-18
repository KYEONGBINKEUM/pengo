"""Local PSD publishing pipeline. Input PHP/JS is inspected, never executed."""
from __future__ import annotations
import argparse, collections, hashlib, html, json, math, re, shutil, zipfile
from pathlib import Path, PurePosixPath
from string import Template
import tinycss2
from psd_tools import PSDImage

import sys
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))  # PyInstaller 번들 대응

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')

def save_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2))

def primitive(value):
    if hasattr(value, 'items'): return {str(primitive(k)): primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or type(value).__name__ == 'List': return [primitive(v) for v in value]
    if hasattr(value, 'value'): return primitive(value.value)
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    return str(value)

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def decode(data):
    for enc in ('utf-8-sig', 'cp949'):
        try: return data.decode(enc), enc
        except UnicodeDecodeError: pass
    return data.decode('utf-8', errors='replace'), 'utf-8-replacement'

def analyze_zip(path):
    """Bound archive reads; do not extract or execute the supplied application."""
    sources, inventory = {}, []
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 20000 or sum(i.file_size for i in z.infolist()) > 512*1024**2:
            raise ValueError('ZIP 크기 제한: 파일 20,000개 / 압축 해제 512MB')
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('안전하지 않은 ZIP 경로: ' + name)
            inventory.append({'path':name, 'bytes':info.file_size})
            if p.suffix.lower() in ('.php', '.html', '.css', '.js') and info.file_size < 2*1024**2:
                text, enc = decode(z.read(info)); sources[name] = (text, enc)
    cssrules, media, classes, includes, libraries = [], [], collections.Counter(), [], set()
    for name, (text, enc) in sources.items():
        if name.endswith('.css'):
            def visit(nodes, context=''):
                for n in nodes:
                    if n.type == 'at-rule' and n.lower_at_keyword == 'media' and n.content:
                        query=tinycss2.serialize(n.prelude).strip(); media.append({'file':name,'line':n.source_line,'query':query})
                        visit(tinycss2.parse_rule_list(n.content, skip_whitespace=True, skip_comments=True), query)
                    elif n.type == 'qualified-rule':
                        ds={d.lower_name:tinycss2.serialize(d.value).strip() for d in tinycss2.parse_declaration_list(n.content) if d.type=='declaration'}
                        cssrules.append({'file':name,'line':n.source_line,'selector':tinycss2.serialize(n.prelude).strip(),'media':context,'declarations':ds})
            visit(tinycss2.parse_stylesheet(text,skip_whitespace=True,skip_comments=True))
        if name.endswith(('.php','.html')):
            for m in re.finditer(r'\bclass=["\']([^"\']+)', text): classes.update(m[1].split())
            for m in re.finditer(r'\b(?:include|require)(?:_once)?\s*(?:\([^;]+\)|[^;]+);', text):
                includes.append({'file':name,'line':text[:m.start()].count('\n')+1,'code':m[0]})
        for key, pattern in [('jquery',r'jquery|\$\(document\)'),('slick',r'\.slick\(|slick.min.js'),('aos',r'data-aos|AOS.init'),('gnuboard',r'G5_|pg/common.php')]:
            if re.search(pattern,text,re.I): libraries.add(key)
    def declaration(selector, prop, default):
        matches=[r for r in cssrules if r['selector']==selector and not r['media'] and prop in r['declarations']]
        return matches[-1]['declarations'][prop] if matches else default
    # One source project gives observed conventions, not organization-wide certainty.
    return {'schema_version':1,'source_sha256':sha(path),'inventory':inventory,
            'encodings':{k:v[1] for k,v in sources.items()},'classes':classes.most_common(40),
            'includes':includes,'css_rules':cssrules,'media':media,'libraries':sorted(libraries),
            'generation':{'inner_width':declaration('.inner','width','1400px'),
                          'wide_width':declaration('.w-inner','width','1600px'),
                          'font_family':declaration('body','font-family',"'Pretendard', 'Malgun Gothic', sans-serif"),
                          'brand_color':declaration(':root','--color1','#227fcb'),
                          'breakpoints':sorted({int(x) for r in media for x in re.findall(r'max-width\s*:\s*(\d+)px',r['query'])},reverse=True),
                          'header':'inc/head.php','top':'inc/top.php','footer':'inc/bottom.php'},
            'limitations':['단일 프로젝트에서 관찰한 규칙입니다.','기존 PHP·JS는 실행하지 않았습니다.','그누보드 DB·pg/common.php는 별도 연동이 필요합니다.']}

def prog(pct, msg):
    print(f'@@PROGRESS {int(pct)} {msg}', flush=True)


def inspect_psd(path, dest):
    prog(3, 'PSD 파일을 여는 중 (용량이 크면 시간이 걸립니다)')
    print('PSD 레이어와 텍스트 분석 중...', flush=True)
    psd=PSDImage.open(path)
    if psd.width*psd.height > 60_000_000: raise ValueError('MVP 처리 제한: 6천만 픽셀')
    layers=list(psd.descendants()); ids={id(l):f'L{i:04d}' for i,l in enumerate(layers)}
    prog(10, f'레이어 {len(layers)}개를 찾았습니다 · 글자 스타일 분석 중')
    rows=[]; warnings=[]
    for li,l in enumerate(layers):
        if li%12==0: prog(10+20*li/max(1,len(layers)), f'레이어·글자 스타일 분석 중 ({li}/{len(layers)})')
        parent=ids.get(id(l.parent)); chain=[]; p=l
        while p is not psd: chain.append(p.name); p=p.parent
        row={'id':ids[id(l)],'name':l.name,'path':'/'.join(reversed(chain)),'parent':parent,
             'kind':l.kind,'bbox':list(l.bbox),'visible':l.visible,'effective_visible':l.is_visible(),
             'opacity':l.opacity/255,'clipping':l.clipping,'blend_mode':str(l.blend_mode)}
        if l.kind=='type':
            row['text']=l.text.replace('\r','\n').replace('\x03','\n'); row['transform']=list(l.transform)
            try:
                engine=primitive(l.engine_dict); resources=primitive(l.resource_dict)
                fonts=resources['FontSet']; styles=engine['StyleRun']; pos=0; runs=[]
                sy=math.hypot(l.transform[2],l.transform[3]); sx=math.hypot(l.transform[0],l.transform[1])
                for run,length in zip(styles['RunArray'],styles['RunLengthArray']):
                    d=run['StyleSheet']['StyleSheetData']; fname=fonts[int(d.get('Font',0))]['Name']; fs=float(d.get('FontSize',16))*sy
                    values=d.get('FillColor',{}).get('Values',[1,0,0,0]); color='#'+''.join(f'{max(0,min(255,round(float(c)*255))):02x}' for c in values[1:4])
                    # Photoshop offsets count UTF-16 code units, including surrogate pairs.
                    raw=l.text.encode('utf-16-le'); substring=raw[pos*2:(pos+length)*2].decode('utf-16-le',errors='replace').replace('\r','\n').replace('\x03','\n'); pos+=length
                    weight=next((v for k,v in [('extrabold',800),('semibold',600),('bold',700),('medium',500),('light',300),('thin',100)] if k in fname.lower()),400)
                    leading=fs*1.2 if d.get('AutoLeading',True) else float(d.get('Leading',fs*1.2))*sy
                    runs.append({'text':substring,'font':fname,'font_family':fname.split('-')[0],'font_size_px':fs,'weight':weight,'color':color,'line_height_px':leading,'letter_spacing_px':float(d.get('Tracking',0))/1000*fs,'raw_style':d})
                row.update(runs=runs,paragraphs=engine.get('ParagraphRun'),scale_x=sx,scale_y=sy)
            except Exception as e: warnings.append({'layer':row['id'],'issue':'text_style','detail':str(e)})
        rows.append(row)
    manifest={'schema_version':1,'source_sha256':sha(path),'width':psd.width,'height':psd.height,
              'counts':dict(collections.Counter(l.kind for l in layers)), 'layers':rows,'warnings':warnings}
    prog(30, '전체 미리보기 이미지를 만드는 중')
    dest.mkdir(parents=True,exist_ok=True)
    merged=psd.topil()
    if merged is None: merged=psd.composite()
    merged.convert('RGB').save(dest/'reference.png')
    preview=merged.copy(); preview.thumbnail((960,4000)); preview.convert('RGB').save(dest/'reference-preview.jpg',quality=88)
    prog(36, '분석 결과를 저장하는 중')
    save_json(dest/'layers.json',manifest)
    tokens={'font_sizes_px':collections.Counter(round(run['font_size_px'],2) for row in rows for run in row.get('runs',[])).most_common(),
            'font_names':collections.Counter(run['font'] for row in rows for run in row.get('runs',[])).most_common(),
            'text_colors':collections.Counter(run['color'] for row in rows for run in row.get('runs',[])).most_common(),
            'group_geometry':[]}
    for group in (row for row in rows if row['kind']=='group'):
        children=[row for row in rows if row['parent']==group['id'] and row['effective_visible']]
        ordered=sorted(children,key=lambda row:(row['bbox'][1],row['bbox'][0]))
        tokens['group_geometry'].append({'group':group['id'],'children':[row['id'] for row in ordered],
            'vertical_gaps_px':[b['bbox'][1]-a['bbox'][3] for a,b in zip(ordered,ordered[1:])],
            'note':'음수 간격은 겹침입니다. 원시 좌표 관찰이며 flex 간격 확정값이 아닙니다.'})
    save_json(dest/'design-tokens.json',tokens)
    return psd,layers,manifest

class Renderer:
    def __init__(self,psd,layers,manifest,out):
        self.psd,self.layers,self.manifest,self.out=psd,layers,manifest,out
        self.rows={r['id']:r for r in manifest['layers']}; self.byid={f'L{i:04d}':l for i,l in enumerate(layers)}
        self.assets=[]; self.issues=[]; self.bindings=[]; self.cache={}

    def resolve(self, ref):
        if ref in self.byid: return ref
        matches=[r['id'] for r in self.rows.values() if r['path']==ref]
        if len(matches)!=1: raise ValueError(f'레이어 경로가 없거나 중복됩니다: {ref}')
        return matches[0]

    def text(self, ref, tag='p', cls=''):
        rid=self.resolve(ref); r=self.rows[rid]
        if r['kind']!='type': raise ValueError(f'텍스트 레이어가 아닙니다: {ref}')
        self.bindings.append({'layer':rid,'role':'text'})
        txt=html.escape(r['text'].strip()).replace('\n','<br>')
        return f'<{tag} class="{cls}" data-layer="{rid}">{txt}</{tag}>'

    def asset(self,ref,strip_text=True,crop=None):
        rid=self.resolve(ref); key=(rid,strip_text,tuple(crop) if crop else None)
        if key in self.cache: return self.cache[key]
        l=self.byid[rid]; name=f'{rid}-{"art" if strip_text else "full"}'+('-crop' if crop else '')+'.png'
        dest=self.out/'images'/'main'/name; dest.parent.mkdir(parents=True,exist_ok=True)
        def filt(x): return x.is_visible() and (not strip_text or x.kind!='type') and (not strip_text or x.name not in ('dots','btn'))
        image=l.composite(force=True,layer_filter=filt)
        if image is None: raise ValueError(f'이미지 추출 불가: {rid} {l.name}')
        if crop: image=image.crop(tuple(crop))
        image.save(dest)
        rel='images/main/'+name; self.cache[key]=rel
        self.assets.append({'layer':rid,'path':rel,'width':image.width,'height':image.height,'text_removed':strip_text,'crop':crop})
        return rel

    def image(self,ref,cls='',strip_text=True,crop=None,alt=''):
        return f'<img class="{cls}" src="{self.asset(ref,strip_text,crop)}" alt="{html.escape(alt,quote=True)}" loading="lazy">'

    def semantic(self,recipe):
        """Reusable components. The sample recipe is an explicit human mapping."""
        h=recipe['header']; nav=''.join(f'<a href="{html.escape(x[1],quote=True)}">{html.escape(x[0])}</a>' for x in h['nav'])
        top=f'<header id="header"><div class="w-inner"><a class="logo" href="#content">{self.image(h["logo"],strip_text=False,alt=recipe["title"])}</a><button class="menu-toggle" aria-expanded="false" aria-controls="site-nav">메뉴</button><nav id="site-nav" aria-label="주 메뉴">{nav}</nav><span class="account">로그인 · 회원가입</span></div></header>'
        parts=[]
        for sec in recipe['sections']:
            kind=sec['component']; sid=sec['id']
            if kind=='hero':
                def tile(t,cls):
                    body=self.image(t['art'],'tile-art')+''.join(self.text(v['layer'],v.get('tag','p'),v.get('class','')) for v in t['texts'])
                    return f'<article class="{cls}"><div class="text">{body}</div></article>'
                content=tile(sec['primary'],'hero-primary')+tile(sec['banner'],'hero-banner')+''.join(tile(t,'hero-small') for t in sec['cards'])
                parts.append(f'<section id="{sid}" class="w-inner hero-grid">{content}</section>')
            elif kind=='links':
                items=''.join(f'<a href="{x.get("href","#sec1")}">{self.image(x["icon"])}{self.text(x["text"],"span")}</a>' for x in sec['items'])
                parts.append(f'<section id="{sid}" class="inner quick-links" aria-label="바로가기">{items}</section>')
            elif kind=='courses':
                cards=[]
                for c in sec['items']:
                    category=self.rows[self.resolve(c['category'])]['text']
                    card=self.image(c['image'],'course-image',crop=c.get('crop'))+self.text(c['status'],'span','badge')
                    card+='<div class="txt">'+self.text(c['category'],'p','category')+self.text(c['title'],'h3')+'<div class="course-meta">'+self.text(c['labels'])+self.text(c['values'])+'</div></div>'
                    cards.append(f'<article class="course-card" data-category="{html.escape(category,quote=True)}">{card}</article>')
                buttons=''.join(f'<button type="button" data-filter="{html.escape(v,quote=True)}" aria-pressed="{str(i==0).lower()}">{html.escape(v)}</button>' for i,v in enumerate(sec['filters']))
                parts.append(f'<section id="{sid}" class="courses"><div class="inner"><div class="m_txt flex">{self.text(sec["title"],"h2")}<div class="filters" aria-label="교육 분류">{buttons}</div></div><div class="course-list" tabindex="0" aria-label="교육 목록, 가로 스크롤 가능">{"".join(cards)}</div></div></section>')
            elif kind=='boards':
                boards=[]
                for board in sec['items']:
                    items=''.join('<li>'+self.text(x['title'],'h3')+(self.text(x['description'],'p','description') if x.get('description') else '')+self.text(x['date'],'p','date')+'</li>' for x in board['items'])
                    boards.append('<article class="board">'+self.text(board['title'],'h2')+f'<ul>{items}</ul>'+self.text(board['more'],'p','more')+'</article>')
                parts.append(f'<section id="{sid}" class="inner boards">{"".join(boards)}</section>')
            elif kind=='faq':
                entries=[]
                for i,q in enumerate(sec['items']):
                    answer=self.text(q['answer']) if q.get('answer') else '<p>원본 PSD에 답변 내용이 없습니다. 운영 콘텐츠를 입력해 주세요.</p>'
                    entries.append(f'<details {"open" if i==0 else ""}><summary>{self.text(q["question"],"span")}</summary>{answer}</details>')
                art=self.image(sec['art'],'tile-art')+self.text(sec['label'],'p','eyebrow')+self.text(sec['caption'],'p','caption')
                parts.append(f'<section id="{sid}" class="inner faq"><div class="faq-art">{art}</div><div class="faq-list">{"".join(entries)}</div></section>')
            elif kind=='logos':
                parts.append(f'<section id="{sid}" class="inner partners" aria-label="협력 기관">'+''.join(self.image(ref,strip_text=False) for ref in sec['items'])+'</section>')
            else: raise ValueError('지원하지 않는 컴포넌트: '+kind)
        f=recipe['footer']
        bottom='<footer id="footer"><div class="inner">'+self.image(f['logo'],'footer-logo',strip_text=False)+self.text(f['terms'],'p','terms')+self.text(f['address'],'p','info')+self.text(f['copyright'],'p','copyright')+'</div></footer><button class="go-top" type="button" aria-label="맨 위로">↑</button>'
        return top,'<main id="content">'+''.join(parts)+'</main>',bottom

    def draft(self):
        """Any PSD: editable DOM text over per-section artwork; small-screen reading layout."""
        groups=[l for l in self.psd if l.is_group() and l.is_visible() and l.width and l.height]
        # Loose text/art outside groups must not silently disappear. A full-page
        # coordinate draft is safer in this case than guessing a section boundary.
        loose=[l for l in self.psd if not l.is_group() and l.is_visible() and l.width and l.height
               and not (l.kind=='pixel' and l.bbox==(0,0,self.psd.width,self.psd.height))]
        if not groups or loose: groups=[self.psd]
        sections=[]; styles=[]; warnings=['자동 초안: 데스크톱 좌표 배치 및 모바일 읽기 순서 추정. 의미 구조/링크/동작은 검토가 필요합니다.']
        for i,g in enumerate(groups):
            gid='root' if g is self.psd else self.resolve(next(r['path'] for r in self.rows.values() if self.byid[r['id']] is g))
            members=list(g.descendants())
            texts=[self.rows[f'L{self.layers.index(l):04d}'] for l in members if l.kind=='type' and l.is_visible()]
            texts.sort(key=lambda r:(r['bbox'][1],r['bbox'][0]))
            if g is self.psd:
                img=g.composite(force=True,layer_filter=lambda x:x.is_visible() and x.kind!='type'); path='images/main/root-art.png'; (self.out/'images/main').mkdir(parents=True,exist_ok=True); img.save(self.out/path)
                x,y,w,h=0,0,g.width,g.height
            else:
                path=self.asset(gid); x,y,xx,yy=g.bbox; w,h=xx-x,yy-y
            content=[]
            for r in texts:
                rid=r['id']; bx,by,ex,ey=r['bbox']; run=(r.get('runs') or [{}])[0]; fs=run.get('font_size_px',16)
                spans=''.join(f'<span style="color:{rr["color"]};font-weight:{rr["weight"]};font-size:{rr["font_size_px"]/fs:.5f}em;font-family:{html.escape(rr["font_family"],quote=True)},sans-serif">{html.escape(rr["text"]).replace(chr(10),"<br>")}</span>' for rr in r.get('runs',[])) or html.escape(r['text']).replace('\n','<br>')
                content.append(f'<p class="psd-text" data-layer="{rid}">{spans}</p>'); self.bindings.append({'layer':rid,'role':'draft-text'})
                # Container query units make a coordinate draft scale without JS.
                styles.append(f'#{gid} [data-layer="{rid}"]{{left:{(bx-x)/w*100:.5f}%;top:{(by-y)/h*100:.5f}%;width:{(ex-bx+8)/w*100:.5f}%;font-size:{fs/w*100:.5f}cqw;line-height:{run.get("line_height_px",fs*1.2)/fs:.4f};letter-spacing:{run.get("letter_spacing_px",0)/fs:.4f}em;opacity:{r["opacity"]};}}')
            sections.append((y,f'<section id="{gid}" class="draft-section" style="aspect-ratio:{w}/{h};width:{w/self.psd.width*100:.5f}%;left:{x/self.psd.width*100:.5f}%;top:{y/self.psd.height*100:.5f}%;z-index:{i}" aria-label="{html.escape(g.name,quote=True)}"><img class="draft-art" src="{path}" alt=""><div class="draft-texts">{"".join(content)}</div></section>'))
        self.issues.extend(warnings+['모바일 자동 초안은 이미지와 텍스트를 순서대로 표시하는 읽기용 레이아웃입니다. 컴포넌트별 반응형 디자인은 레시피로 보완하세요.', '회전·기울임·문단 정렬·그룹 혼합 효과·클리핑 텍스트는 브라우저에서 완전히 재현하지 않습니다.', '단일 평면 이미지 PSD는 이미지로만 출력됩니다. OCR이나 의미 구조 복원은 수행하지 않습니다.'])
        css='\n'.join(styles)+ '\n.draft-canvas{position:relative;overflow:hidden;background:white}.draft-section{position:absolute;container-type:inline-size;overflow:hidden}.draft-art{width:100%;height:100%;display:block}.psd-text{position:absolute;margin:0;white-space:pre-wrap}.draft-notice{padding:16px;background:#eef6fc;color:#172d40}@media(max-width:768px){.draft-canvas{aspect-ratio:auto!important}.draft-section{position:relative;left:auto!important;top:auto!important;width:100%!important;aspect-ratio:auto!important;margin-bottom:24px}.draft-art{height:auto;width:auto;max-width:100%;max-height:480px;object-fit:contain;margin:auto}.draft-texts{padding:20px;display:grid;gap:12px}.draft-section .psd-text{position:static!important;width:auto!important;font-size:16px!important;opacity:1!important;line-height:1.5!important}.psd-text span{color:#172d40!important}}'
        write(self.out/'css/draft.css',css)
        return '', '<main id="content"><p class="draft-notice">자동 배치 초안 · 링크와 동작은 설정이 필요합니다.</p><div class="draft-canvas" style="aspect-ratio:'+str(self.psd.width)+'/'+str(self.psd.height)+'">'+''.join(s for y,s in sorted(sections))+'</div></main>', ''

def find_browser():
    """일치율 측정용 브라우저: Edge(윈도우 기본 포함) → Chrome 순서."""
    import os
    for c in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
              r'C:\Program Files\Google\Chrome\Application\chrome.exe', r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'):
        if os.path.exists(c): return c
    return None


def measure_match(out, manifest=None, sec_ranges=None, elems=None):
    """생성된 preview.html을 브라우저로 캡처해 PSD 합성본(analysis/reference.png)과 픽셀 단위로 비교한다.
    일치율(%) = 100 × (1 − 밝기 차이가 40을 넘는 픽셀의 비율). 측정 불가면 None."""
    import os, subprocess, tempfile, time
    from PIL import Image, ImageChops
    import numpy as np
    browser = find_browser()
    if not browser: return None, 0
    ref = Image.open(out/'analysis'/'reference.png').convert('RGB'); W, H = ref.size
    tmp = Path(tempfile.gettempdir()); tag = f'psdpub-{os.getpid()}'
    shot, profile = tmp/(tag+'.png'), tmp/(tag+'-profile')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        for _ in range(3):
            try:
                subprocess.run([browser, f'--user-data-dir={profile}', '--headless=new', '--disable-gpu', '--hide-scrollbars', f'--window-size={W},{H+400}',
                                '--virtual-time-budget=6000', f'--screenshot={shot}', (out/'preview.html').as_uri()], capture_output=True, timeout=90, creationflags=flags)
            except Exception: pass
            if shot.exists(): break
            time.sleep(1.5)
        if not shot.exists(): return None, 0
        page = Image.open(shot).convert('RGB'); h = min(page.height, H)
        diff = np.array(ImageChops.difference(page.crop((0, 0, W, h)), ref.crop((0, 0, W, h))).convert('L')) > 40
        bad = int(diff.sum()) + (H - h) * W   # 페이지가 더 짧으면 모자란 줄은 전부 불일치
        pct = max(0.0, 100.0 * (1 - bad / float(W * H)))
        n_reg = 0
        try:  # 앱 미리보기용 변환 화면 (PSD 미리보기와 같은 크기)
            pv = page.crop((0, 0, W, h)); pv.thumbnail((960, 4000)); pv.save(out/'analysis'/'result-preview.jpg', quality=88)
        except Exception: pass
        try:  # 불일치 구간 보고서(HTML·JSON·MD + 구간 이미지)
            import mismatch
            n_reg = mismatch.build_report(out, ref, page, pct, manifest or {}, sec_ranges or {}, elems or [])
        except Exception as e:
            print('불일치 보고서 생성 실패: '+str(e),flush=True)
        return pct, n_reg
    except Exception:
        return None, 0
    finally:
        try: shot.unlink()
        except Exception: pass
        shutil.rmtree(profile, ignore_errors=True)


# ---------- 생성 HTML 정리: 들여쓰기 + 줄바꿈 ----------
from html.parser import HTMLParser as _HP

_VOID = {'img', 'br', 'input', 'meta', 'link', 'hr'}
_INLINE_OK = {'span', 'b', 'em', 'strong', 'i', 'br'}


class _N:
    __slots__ = ('tag', 'start', 'kids')

    def __init__(self, tag, start): self.tag, self.start, self.kids = tag, start, []


class _Tree(_HP):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = _N('#root', ''); self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = _N(tag, self.get_starttag_text()); self.stack[-1].kids.append(n)
        if tag not in _VOID: self.stack.append(n)

    def handle_startendtag(self, tag, attrs): self.stack[-1].kids.append(_N(tag, self.get_starttag_text()))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, d): self.stack[-1].kids.append(d)
    def handle_entityref(self, name): self.stack[-1].kids.append(f'&{name};')
    def handle_charref(self, name): self.stack[-1].kids.append(f'&#{name};')
    def handle_pi(self, data): self.stack[-1].kids.append('<?' + data + '>')
    def handle_comment(self, data): self.stack[-1].kids.append('<!--' + data + '-->')


def _inline(n):
    if isinstance(n, str): return n
    if n.tag in _VOID: return n.start
    return n.start + ''.join(_inline(k) for k in n.kids) + f'</{n.tag}>'


def _inline_only(n):
    """글자·<br>·<span>·<b> 만 들어 있으면 한 줄로 쓴다. div 안에 <img> 하나, li 안에 <a> 하나도 한 줄."""
    if n.tag in ('ul', 'ol', 'main', 'section', 'header', 'footer', 'aside', 'nav'): return False
    for k in n.kids:
        if isinstance(k, str) or k.tag in _INLINE_OK: continue
        if k.tag == 'img' and n.tag == 'div' and len(n.kids) == 1: continue
        if k.tag == 'a' and n.tag == 'li' and len(n.kids) == 1: continue
        return False
    return True


def _emit(n, level, out):
    pad = '    ' * level
    if isinstance(n, str):
        if n.strip(): out.append(pad + n.strip())
    elif n.tag in _VOID: out.append(pad + n.start)
    elif _inline_only(n): out.append(pad + _inline(n))
    else:
        out.append(pad + n.start)
        for k in n.kids: _emit(k, level + 1, out)
        out.append(pad + f'</{n.tag}>')


def pretty_html(src):
    """한 줄로 이어 붙은 HTML을 블록 요소마다 줄을 나누고 4칸 들여쓰기로 정리한다. 글자 내용은 바꾸지 않는다."""
    t = _Tree(); t.feed(src); t.close(); out = []
    for k in t.root.kids: _emit(k, 0, out)
    return '\n'.join(out)


NAV_PH = '<!--PSDPUB_NAV-->'


def split_nav(header_html, base):
    """헤더의 ul.gnb 메뉴를 inc/nav.php 로 분리한다. 반환: (ul 안을 include 자리표시로 바꾼 헤더, nav.php 내용, 미리보기용 li, [(번호, 코드)], 링크코드 목록)"""
    m = re.search(r'<ul class="gnb">(.*?)</ul>', header_html, re.S)
    if not m: return header_html, None, None, [], []
    labels = re.findall(r'<li><a href="#">(.*?)</a></li>', m.group(1), re.S)
    if not labels: return header_html, None, None, [], []
    codes_file = base / 'nav-codes.json'   # 메뉴 이름 → GoPage 코드 (없는 이름은 menu1, menu2 …)
    cmap = json.loads(codes_file.read_text(encoding='utf-8-sig')) if codes_file.exists() else {}
    php, prev, codes = [], [], []
    for i, lab in enumerate(labels, 1):
        code = cmap.get(html.unescape(lab).strip(), f'menu{i}')
        codes.append(code)
        php.append(f'<li class="gnb_dp1">\n    <div><a href="javascript:GoPage(\'{code}\')">{lab}</a></div>\n    <? include "s_gnb{i}.php" ?>\n</li>')
        prev.append(f'<li class="gnb_dp1"><div><a href="#">{lab}</a></div></li>')
    new_header = header_html[:m.start()] + '<ul class="gnb">' + NAV_PH + '</ul>' + header_html[m.end():]
    return new_header, '\n'.join(php) + '\n', prev, codes, labels


def wide_block():
    import semantic as sem
    c, w = sem.WCLS, sem.WIDE
    return f"/* {c} (넓은 컨테이너) */\n.{c} {{\twidth:{w}px;\tposition:relative;\tmargin-left:auto;\tmargin-right:auto;}}\n@media all and (max-width:{w - 1}px) {{\t.{c} {{width:94%;}}\t}}\n\n"


def merged_frame(frame):
    """회사 기본틀(번들) 위에 사용자 기본틀 폴더를 덮어 쓴 임시 폴더를 만든다. 사용자 폴더에 없는 파일은 기본값을 쓴다."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix='pengo-frame-'))
    shutil.copytree(BASE/'templates'/'base', d, dirs_exist_ok=True)
    if frame and Path(frame).is_dir(): shutil.copytree(frame, d, dirs_exist_ok=True)
    return d


def load_conv(frame):
    """기본틀 폴더의 pengo-rules.json 을 읽어 규칙(이름·폭)을 적용한다. 반환: 경고 목록"""
    import semantic as sem, mismatch
    conv = None
    f = Path(frame)/'pengo-rules.json' if frame else None
    if f and f.is_file():
        try: conv = json.loads(f.read_text(encoding='utf-8-sig'))
        except Exception as e: conv = None; warn0 = [f'pengo-rules.json 을 읽지 못해 기본 규칙을 씁니다: {e}']
        else: warn0 = []
    else: warn0 = []
    warn = warn0 + sem.set_conv(conv)
    mismatch.SELS = ', '.join(f'#{x} *' for x in (sem.HID, sem.CID, sem.FID, sem.QID))
    return warn


def write_base_site(out,parts,title,frame=None):
    """회사 기본틀(templates/base)을 그대로 사용하고 그 위에 생성 결과를 얹는다.
    inc/head.php·inc/bottom.php·inc/top.php, css/default.css(폰트 정의·reset)는 기본틀 파일.
    header → inc/top.php, footer(+퀵메뉴) → inc/bottom.php, header·footer CSS → css/layout.css, 섹션 CSS → css/main.css."""
    import semantic as sem
    base=merged_frame(frame)
    shutil.copytree(base/'css',out/'css',dirs_exist_ok=True); shutil.copytree(base/'js',out/'js',dirs_exist_ok=True)
    (out/'inc').mkdir(parents=True,exist_ok=True)
    esc=lambda x:x.replace('<?','&lt;?')   # PSD 문구 속 PHP 여는 태그 무력화
    head=(base/'inc'/'head.php').read_text(encoding='utf-8').replace('<title></title>','<title>'+html.escape(title)+'</title>')
    fl=''.join(f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={g}:wght@300;400;500;600;700&display=swap" />\n' for g in parts.get('fonts',[]))
    if fl: head=head.replace('</head>', fl+'</head>')   # PSD에서 쓴 글꼴(예: Noto Serif KR)을 불러온다
    header_ph, nav_php, nav_prev, nav_codes, nav_labels = split_nav(parts['header'], base)
    # 로고: 헤더 맨 왼쪽의 그림만 있는 묶음 → h1#logo > a[href="/"]
    mlogo=None; lcd='<div class="'+sem.LC+'">'; st=header_ph.find(lcd)
    if st>=0:   # 짝이 맞는 </div> 찾기
        depth=0
        for m in re.finditer(r'<div\b|</div>',header_ph[st:]):
            depth+=1 if m.group(0)!='</div>' else -1
            if depth==0: en=st+m.end(); break
        inner=header_ph[st+len(lcd):en-6]
        if '<img' in inner and not re.search(r'<ul|<li|<nav',inner): mlogo=(st,en,inner)
    if mlogo:
        header_ph=header_ph[:mlogo[0]]+'<h1 id="logo" class="'+sem.LC+'"><a href="/">'+mlogo[2]+'</a></h1>'+header_ph[mlogo[1]:]
        parts['layout_css']+='\n#logo a{display: contents;}\n'
    link=(base/'inc'/'link.php').read_text(encoding='utf-8')
    if nav_php:
        write(out/'inc/nav.php', nav_php)
        for i in range(1, len(nav_codes)+1):   # 하위(2차) 메뉴 자리: 비어 있는 틀 (include 오류 방지)
            write(out/f'inc/s_gnb{i}.php', f'<!-- 메뉴 {i}의 하위(2차) 메뉴를 여기에 만드세요 -->\n')
        add=''.join(f'\telse if ( code == "{c}" )\t\t{{\twindow.location = "/doc/{c}.php"; }}\r\n' for c in nav_codes if f'"{c}"' not in link)
        j=link.rfind('}',0,link.rfind('</script>'))
        link=link[:j]+add+'\r\n'+link[j:]
    write(out/'inc/link.php', link)
    top='<!-- header -->\n'+esc(pretty_html(header_ph)).replace(NAV_PH,'<?php include "nav.php"; ?>')+'\n<!-- //header -->'
    footer='<!-- footer -->\n'+esc(pretty_html(parts['footer']))+'\n<!-- //footer -->'
    if parts['quick']: footer+='\n\n<!-- quick -->\n'+esc(pretty_html(parts['quick']))+'\n<!-- //quick -->'
    btxt=(base/'inc'/'bottom.php').read_text(encoding='utf-8')
    if '<!-- footer -->' in btxt and '<!-- //footer -->' in btxt: bottom=re.sub(r'<!-- footer -->.*?<!-- //footer -->',lambda m:footer,btxt,flags=re.S)
    elif '</body>' in btxt: bottom=btxt.replace('</body>',footer+'\n</body>',1)   # 내 기본틀에 <!-- footer --> 표시가 없으면 </body> 앞에 넣는다
    else: bottom=btxt+'\n'+footer
    write(out/'inc/head.php',head); write(out/'inc/top.php',top); write(out/'inc/bottom.php',bottom)
    layout=(base/'css'/'layout.css').read_text(encoding='utf-8')
    if sem.INNER!=1400:   # 기본틀의 .inner 폭을 설정(또는 자동 인식)한 폭으로
        layout=re.sub(r'(\.inner\s*\{\s*width:)1400px',lambda m:m.group(1)+f'{sem.INNER}px',layout).replace('max-width:1399px',f'max-width:{sem.INNER-1}px')
    if sem.BCLS!='inner': layout=re.sub(r'\.inner(?![\w-])','.'+sem.BCLS,layout)
    layout=re.sub(r'/\* footer \*/.*','',layout,flags=re.S).rstrip()+'\n\n'+wide_block()+parts['layout_css']+'\n'   # 기본틀의 고정 높이 #footer 규칙은 PSD 값으로 대체
    write(out/'css/layout.css',layout); write(out/'css/main.css','@charset "utf-8";\n\n'+parts['main_css']+'\n')
    content=esc(pretty_html(parts['main']))
    write(out/'index.php','<?//php include_once "_common.php"; ?>\n<?php include "inc/head.php"; ?>\n<?php include "inc/link.php"; ?>\n<?php include "inc/top.php"; ?>\n\n<!-- Content -->\n'+content+'\n<!-- //Content -->\n\n<?php include "inc/bottom.php"; ?>\n')
    # 서버 없이 열어보는 미리보기: 절대경로(/css/…)를 상대경로로, PHP 조각은 제거
    top_prev=top.replace('<?php include "nav.php"; ?>','\n'.join('        '+x for x in nav_prev)) if nav_prev else top   # 미리보기에는 메뉴를 그대로 펼쳐 넣는다(PHP 없이도 보이게)
    prev=re.sub(r'<\?.*?\?>','',head+top_prev+'\n'+content+'\n'+bottom,flags=re.S)
    prev=re.sub(r'(href|src)="/(?!/)',r'\1="',prev)
    def inline_css(m):   # 미리보기는 서버가 없으므로 CSS 를 안에 넣고 url(/images/…)을 상대경로로 바꾼다
        f=out/'css'/(m.group(1)+'.css')
        return '<style>'+f.read_text(encoding='utf-8').replace('url(/','url(')+'</style>' if f.exists() else m.group(0)
    prev=re.sub(r'<link[^>]*href="css/(layout|main)\.css[^"]*"[^>]*>',inline_css,prev)
    write(out/'preview.html',prev)
    shutil.rmtree(base,ignore_errors=True)

def build(psd_path,out,source_zip=None,rules_path=None,recipe_path=None,structure=False,only=None,img_quality='lossless',psd_scale=1,img_scale=1,css_round='tidy',frame=None):
    prog(1, '준비하는 중')
    conv_warn=load_conv(frame)
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()): raise ValueError('출력 폴더가 비어 있지 않습니다. 새 폴더를 선택해 주세요.')
    out.mkdir(parents=True,exist_ok=True)
    if source_zip:
        rules=analyze_zip(source_zip)
    elif rules_path: rules=json.loads(Path(rules_path).read_text(encoding='utf-8-sig'))
    else: rules=json.loads((BASE/'company-rules.json').read_text(encoding='utf-8-sig'))
    save_json(out/'analysis/company-rules.json',rules)
    psd,layers,manifest=inspect_psd(psd_path,out/'analysis')
    r=Renderer(psd,layers,manifest,out)
    if recipe_path:
        recipe=json.loads(Path(recipe_path).read_text(encoding='utf-8-sig'))
        expected=recipe.get('source_sha256')
        if expected and expected!=manifest['source_sha256']: raise ValueError('이 레시피는 다른 PSD용입니다. 새 PSD에는 자동 초안을 사용하거나 경로를 재매핑하세요.')
        top,body,bottom=r.semantic(recipe); mode='semantic-recipe'; title=recipe['title']
        save_json(out/'analysis/recipe.json',recipe)
        r.issues.extend(recipe.get('limitations',[]))
    elif structure:
        from semantic import Semantic
        sm=Semantic(r,only,img_quality,psd_scale,img_scale,css_round); sm.emit=prog; parts=sm.build(out); r.sec_ranges=sm.sec_ranges; r.elems=parts.get('elems',[]); mode='structure'; title=Path(psd_path).stem
        r.issues.extend(sm.notes); r.issues.extend(conv_warn); prog(88, '기본틀(inc/·css/)에 맞춰 파일을 쓰는 중'+(' (내 기본틀 사용)' if frame else '')); write_base_site(out,parts,title,frame)
    else: top,body,bottom=r.draft(); mode='automatic-draft'; title=Path(psd_path).stem
    if mode!='structure':
        for name in (('default.css','layout.css') if mode=='structure' else ('default.css','layout.css','main.css')):
            content=(BASE/'templates'/name).read_text(encoding='utf-8')
            generation=rules['generation']
            for key in ('inner_width','wide_width','brand_color','font_family'): content=content.replace('{{'+key+'}}',str(generation[key]))
            write(out/'css'/name,content)
        (out/'js').mkdir(exist_ok=True)
        shutil.copyfile(BASE/'templates/main.js',out/'js/main.js')
        head='<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title>'+''.join(f'<link rel="stylesheet" href="css/{n}.css">' for n in (['default','layout','sections'] if mode=='structure' else ['default','layout','main']+(['draft'] if mode=='automatic-draft' else [])))+'</head><body><div id="wrap">\n'
        end='</div><script src="js/main.js"></script></body></html>'
        # Escape PHP open tags present in PSD text without changing browser-visible text.
        top,body,bottom=(x.replace('<?','&lt;?') for x in (top,body,bottom))
        write(out/'inc/head.php',head); write(out/'inc/top.php',top); write(out/'inc/bottom.php',bottom+end)
        write(out/'index.php','<?php include __DIR__."/inc/head.php"; ?>\n<?php include __DIR__."/inc/top.php"; ?>\n'+body+'\n<?php include __DIR__."/inc/bottom.php"; ?>\n')
        write(out/'preview.html',head+top+body+bottom+end)
    prog(90, 'PSD와 얼마나 일치하는지 측정하는 중 (브라우저로 화면을 캡처합니다)')
    match_pct,n_mismatch=measure_match(out,manifest,getattr(r,'sec_ranges',{}),getattr(r,'elems',[]))
    print('@@MATCH '+('-1' if match_pct is None else f'{match_pct:.1f}'),flush=True)
    print(f'@@MISMATCH {n_mismatch}',flush=True)
    if match_pct is None: r.issues.append('PSD 일치율을 측정하지 못했습니다(Edge 또는 Chrome이 필요합니다).')
    else: r.issues.append(f'PSD 합성본과의 화면 일치율: {match_pct:.1f}% (화면 캡처와 픽셀 비교, 글꼴·번짐 차이 포함) · 다른 구간 {n_mismatch}곳은 analysis/mismatch-report.html 참고')
    fonts=sorted({run['font'] for row in manifest['layers'] for run in row.get('runs',[])})
    r.issues.extend(['웹폰트 파일 미포함: 시스템 대체 글꼴로 표시됩니다. 실제 폰트 확보 후 @font-face를 연결하세요.', 'PSD의 문구는 출처 그대로이며 현재 운영 일정이나 실제 신청 상태를 뜻하지 않습니다.', '실제 URL·DB·로그인·신청 처리 및 숨은 슬라이드 콘텐츠는 생성하지 않습니다.'])
    report={'mode':mode,'match_percent':None if match_pct is None else round(match_pct,2),'psd_sha256':manifest['source_sha256'],'canvas':[psd.width,psd.height],
            'counts':manifest['counts'],'fonts':fonts,'assets':r.assets,'text_bindings':r.bindings,
            'unmapped_visible_text':[row['id'] for row in manifest['layers'] if row['kind']=='type' and row['effective_visible'] and row['id'] not in {b['layer'] for b in r.bindings}],
            'issues':r.issues,'style_warnings':manifest['warnings']}
    prog(94, '변환 보고서를 작성하는 중')
    save_json(out/'analysis/build-report.json',report)
    write(out/'README.txt','생성 결과\npreview.html: 더블클릭 미리보기\nindex.php: PHP 서버용\nanalysis/layers.json: PSD 원본 수치 및 텍스트 스타일\nanalysis/company-rules.json: 기존 소스 관찰 규칙\nanalysis/build-report.json: 변환 범위와 미연결 항목\n\n'+'\n'.join(r.issues))
    prog(97, 'ZIP 파일로 압축하는 중')
    archive=shutil.make_archive(str(out)+'-site','zip',out)
    prog(100, '완료')
    print('완료: '+str(out)+'\nZIP: '+archive,flush=True)
    return report

def export_frame(out):
    """내장 회사 기본틀(inc/·css/·js/)과 규칙 파일(pengo-rules.json)을 편집 가능한 폴더로 꺼낸다."""
    import semantic as sem
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    shutil.copytree(BASE/'templates'/'base',out,dirs_exist_ok=True)
    rules={'_도움말':'이 파일의 값으로 변환 규칙(폭·id·클래스 이름)을 바꿉니다. 지우면 기본값을 씁니다.'}
    rules.update(sem.DEFAULT_CONV); rules['inner']='auto'; rules['wide']='auto'   # 폭: auto = PSD 에서 알아냄, 숫자 = 고정
    (out/'pengo-rules.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('완료: '+str(out),flush=True)

def main():
    for s in (sys.stdout, sys.stderr):  # GUI가 UTF-8로 읽으므로 출력 인코딩 고정
        try: s.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
    p=argparse.ArgumentParser(description='회사 스타일 PSD → PHP/CSS/JS 생성기')
    sub=p.add_subparsers(dest='command',required=True)
    x=sub.add_parser('export-frame',help='내장 회사 기본틀을 편집 가능한 폴더로 꺼낸다'); x.add_argument('--out',required=True)
    a=sub.add_parser('analyze-style'); a.add_argument('zip'); a.add_argument('--out',required=True)
    b=sub.add_parser('build'); b.add_argument('psd'); b.add_argument('--out',required=True); b.add_argument('--source-zip'); b.add_argument('--rules'); b.add_argument('--recipe'); b.add_argument('--structure',action='store_true',help='의미 구조 변환(통이미지 대신 요소별 HTML/CSS)'); b.add_argument('--only',action='append',help='이름에 포함된 그룹만 변환(여러 번 지정 가능)'); b.add_argument('--image-quality',choices=['lossless','png','high','normal'],default='lossless',help='이미지 저장: lossless=WebP 무손실(최대화질·기본), png=PNG 무손실, high=WebP 95, normal=WebP 85'); b.add_argument('--psd-scale',type=int,default=1,choices=[1,2,3,4],help='PSD가 몇 배 크기로 만들어졌는지(2x 시안이면 2). 모든 CSS 수치를 이 값으로 나눠 1배 시안과 같은 코드를 만든다'); b.add_argument('--image-scale',type=int,default=1,choices=[1,2,3,4],help='이미지를 몇 배 크기로 저장할지(레티나용). CSS 크기는 그대로'); b.add_argument('--frame',help='기본틀 폴더(없으면 내장 회사 기본틀). 이 폴더의 파일이 기본틀을 덮어쓰고, pengo-rules.json 으로 이름·폭 규칙을 바꾼다'); b.add_argument('--css-round',choices=['tidy','exact'],default='tidy',help='CSS 숫자 정리: tidy=간격을 5px·2px 단위로(깔끔), exact=소수점만 정수로(PSD에 가깝게)')
    args=p.parse_args()
    if args.command=='export-frame': export_frame(args.out)
    elif args.command=='analyze-style': save_json(args.out,analyze_zip(args.zip))
    else: build(args.psd,args.out,args.source_zip,args.rules,args.recipe,args.structure,args.only,args.image_quality,args.psd_scale,args.image_scale,args.css_round,args.frame)

if __name__=='__main__': main()
