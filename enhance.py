"""변환 결과(HTML)를 한 번 더 다듬는 단계: 접근성·SEO, 반복 요소(ul/li), 폼·게시판 요소, 이미지 지연 로딩.
생성된 HTML 조각을 읽어 태그·속성만 바꾸고 글자 내용은 바꾸지 않는다. CSS 선택자는 클래스 기준이라 태그가 바뀌어도 그대로 적용된다."""
import html
import re
from html.parser import HTMLParser

VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'col', 'area', 'base', 'embed', 'track'}
OPTS_DEFAULT = {'a11y': True, 'repeat': True, 'forms': True}


class N:
    """HTML 요소 한 개. attrs 는 [이름, 값] 목록(순서 유지), kids 는 N 또는 문자열(글자·엔티티·주석·PHP)."""
    __slots__ = ('tag', 'attrs', 'kids', 'selfclose')

    def __init__(self, tag, attrs=None, selfclose=False):
        self.tag, self.attrs, self.kids, self.selfclose = tag, attrs or [], [], selfclose

    def get(self, name, default=None):
        for k, v in self.attrs:
            if k == name: return v
        return default

    def set(self, name, value):
        for a in self.attrs:
            if a[0] == name:
                a[1] = value; return
        self.attrs.append([name, value])

    def classes(self): return (self.get('class') or '').split()

    def add_class(self, c):
        cl = self.classes()
        if c not in cl: self.set('class', ' '.join(cl + [c]))


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = N('#root'); self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = N(tag, [[k, v] for k, v in attrs]); self.stack[-1].kids.append(n)
        if tag not in VOID: self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(N(tag, [[k, v] for k, v in attrs], True))

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


def parse(src):
    p = _P(); p.feed(src); p.close()
    return p.root


def _start(n):
    a = ''.join(f' {k}' if v is None else f' {k}="{html.escape(v, quote=True)}"' for k, v in n.attrs)
    return f'<{n.tag}{a}>'


def dump(n):
    if isinstance(n, str): return n
    if n.tag == '#root': return ''.join(dump(k) for k in n.kids)
    if n.tag in VOID: return _start(n)
    return _start(n) + ''.join(dump(k) for k in n.kids) + f'</{n.tag}>'


def elems(n): return [k for k in n.kids if not isinstance(k, str)]


def walk(n, fn, parent=None):
    if isinstance(n, str): return
    fn(n, parent)
    for k in list(n.kids): walk(k, fn, n)


def text_of(n):
    if isinstance(n, str):
        return '' if n.startswith('<!--') or n.startswith('<?') else html.unescape(n)
    if n.tag == 'img': return ''
    if n.tag == 'br': return ' '
    return ''.join(text_of(k) for k in n.kids)


def clean(s): return re.sub(r'\s+', ' ', s).strip()


def has_content(n):
    if isinstance(n, str): return False
    if n.tag == 'img': return True
    return bool(clean(text_of(n))) or any(has_content(k) for k in elems(n))


# ───────────────────────── 접근성 ─────────────────────────
ICON_LABEL = {'←': '이전', '→': '다음', '‹': '이전', '›': '다음', '<': '이전', '>': '다음', '+': '더보기', '＋': '더보기', '×': '닫기', '✕': '닫기', '✖': '닫기', '-': '접기', '↑': '위로', '↓': '아래로', '☰': '메뉴'}


def _heading_text(n):
    """n 안에서 가장 먼저 나오는 제목(h2~h6) 글자"""
    for k in elems(n):
        if k.tag in ('h2', 'h3', 'h4', 'h5', 'h6'):
            t = clean(text_of(k))
            if t: return t
        t = _heading_text(k)
        if t: return t
    return ''


def a11y(root, ctx, stats):
    site = ctx.get('title', '')
    skip_first = ctx.get('first_section')   # 첫 화면(비주얼) 이미지는 즉시 로딩

    def visit(n, parent, anc):
        if n.tag == 'img':
            alt = n.get('alt')
            if not alt:
                lab = ''
                if any(a.get('id') == 'logo' for a in anc): lab = site
                else:
                    for a in reversed(anc[-4:]):
                        if 'bg' in a.classes(): break      # 배경 그림은 장식
                        t = _heading_text(a)
                        if t: lab = t; break
                n.set('alt', lab)
                if lab: stats['alt'] = stats.get('alt', 0) + 1
                else: stats['decor'] = stats.get('decor', 0) + 1
            if ctx.get('lazy') and not any(a.get('id') in skip_first for a in anc) and not any(a.tag == 'header' for a in anc):
                if n.get('loading') is None: n.set('loading', 'lazy'); n.set('decoding', 'async'); stats['lazy'] = stats.get('lazy', 0) + 1
        elif n.tag == 'a':
            t = clean(text_of(n))
            if t in ICON_LABEL and not n.get('aria-label'):
                n.set('aria-label', ICON_LABEL[t]); stats['aria'] = stats.get('aria', 0) + 1
            elif not t and not n.get('aria-label') and not any(isinstance(k, N) and k.tag == 'img' and k.get('alt') for k in _desc(n)):
                lab = site if n.get('href') == '/' else ''
                if lab: n.set('aria-label', lab)
        for k in elems(n): visit(k, n, anc + [n])
    visit(root, None, [])


def _desc(n):
    for k in elems(n):
        yield k
        yield from _desc(k)


def seo_meta(main_html, ctx):
    """<head> 에 넣을 SEO 메타 (설명·Open Graph·Twitter·JSON-LD). 설명은 본문의 첫 문단에서 뽑는다."""
    root = parse(main_html); cand = []

    def v(n, p):
        if n.tag in ('p', 'h1', 'h2', 'h3') :
            t = clean(text_of(n))
            if len(t) >= 20: cand.append(t)
    walk(root, v)
    desc = (cand[0] if cand else ctx.get('title', ''))
    if len(desc) > 110: desc = desc[:108].rstrip() + '…'
    t = html.escape(ctx.get('title', ''), quote=True); d = html.escape(desc, quote=True)
    out = [f'<meta name="description" content="{d}" />', f'<meta property="og:type" content="website" />', f'<meta property="og:title" content="{t}" />',
           f'<meta property="og:description" content="{d}" />', '<meta property="og:locale" content="ko_KR" />', '<meta name="twitter:card" content="summary_large_image" />',
           f'<meta name="twitter:title" content="{t}" />', f'<meta name="twitter:description" content="{d}" />']
    import json
    out.append('<script type="application/ld+json">' + json.dumps({'@context': 'https://schema.org', '@type': 'WebSite', 'name': ctx.get('title', ''), 'description': desc}, ensure_ascii=False) + '</script>')
    return '\n'.join(out) + '\n', desc


SKIP_LINK = '<a class="pg-skip" href="#content">본문 바로가기</a>\n'
SKIP_CSS = '.pg-skip{position:absolute;left:-9999px;top:0;z-index:9999;background:#000;color:#fff;padding:10px 16px}\n.pg-skip:focus{left:0}\n'


# ───────────────────────── 반복 요소 ─────────────────────────
def _base(c): return re.sub(r'\d+$', '', c)


def _sig(n):
    """구조 지문: 태그 + 클래스(끝 숫자 제외) + 자식 구조. 같은 지문이면 같은 모양의 반복 요소."""
    if isinstance(n, str): return None
    cl = ','.join(sorted(_base(c) for c in n.classes()))
    kids = tuple(s for s in (_sig(k) for k in elems(n)) if s)
    return (n.tag, cl, kids)


def repeat(root, stats):
    """같은 모양의 형제가 3개 이상 이어지고 부모에 그것만 있으면 부모를 ul, 자식을 li 로 바꾼다."""
    def visit(n, parent):
        ks = elems(n)
        if (n.tag == 'div' and len(ks) >= 3 and all(k.tag == 'div' for k in ks)
                and all(isinstance(k, N) or not k.strip() for k in n.kids)
                and all(has_content(k) for k in ks) and len({_sig(k) for k in ks}) == 1
                and 'id' not in dict(n.attrs) and not any(k.get('id') for k in ks)):
            n.tag = 'ul'
            for k in ks: k.tag = 'li'
            stats['repeat'] = stats.get('repeat', 0) + 1
    walk(root, visit)


DATE = re.compile(r'^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$')


def semantic_text(root, stats):
    """날짜 문구 → <time datetime>"""
    def visit(n, parent):
        if n.tag == 'p' and len(n.kids) == 1 and isinstance(n.kids[0], str):
            m = DATE.match(clean(html.unescape(n.kids[0])))
            if m:
                tm = N('time', [['datetime', f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}']]); tm.kids = [n.kids[0]]
                n.kids = [tm]; stats['time'] = stats.get('time', 0) + 1
    walk(root, visit)


# ───────────────────────── 폼·게시판 ─────────────────────────
FIELDS = [   # (이름 단서, input type, name)
    (r'비밀번호|패스워드|password', 'password', 'password'), (r'이메일|e-?mail', 'email', 'email'), (r'휴대폰|연락처|전화|핸드폰|tel|phone', 'tel', 'tel'),
    (r'아이디|\bid\b', 'text', 'user_id'), (r'이름|성함|성명|name', 'text', 'name'), (r'주소', 'text', 'address'), (r'제목', 'text', 'subject'),
    (r'희망일|날짜|일자|방문일', 'date', 'date'), (r'검색', 'search', 'q'), (r'문의|내용|메모|메시지|요청|상담', 'textarea', 'message'),
]
PLACEHOLDER = re.compile(r'(입력|선택|검색|작성|적어)[가-힣\s]*(하세요|해주세요|해 주세요|해주십시오|주세요|\.\.\.|…)?\s*$')
SUBMIT = re.compile(r'^(문의\s*하기|신청\s*하기|신청|접수|등록|전송|제출|보내기|로그인|검색|확인|상담\s*신청|예약\s*하기|예약|가입\s*하기|회원가입)$')
BOARD_HEAD = ('번호', '제목', '작성자', '글쓴이', '날짜', '작성일', '등록일', '조회', '조회수', '첨부')


def _field_kind(label):
    for pat, typ, name in FIELDS:
        if re.search(pat, label, re.I): return typ, name
    return None


def _input_for(typ, name, ph, cls, used):
    k = name; i = used.get(name, 0); used[name] = i + 1
    if i: k = f'{name}{i + 1}'
    cl = (cls + ' ' if cls else '') + 'pg-field'
    if typ == 'textarea': return N('textarea', [['class', cl], ['name', k], ['placeholder', ph], ['aria-label', ph or name]])
    return N('input', [['class', cl], ['type', typ], ['name', k], ['placeholder', ph], ['aria-label', ph or name]], True)


def forms(root, stats):
    """입력칸 모양 요소를 input/textarea 로, 제출 문구 링크를 submit 버튼으로, 게시판 표 구조에 role 을 붙인다."""
    used = {}; groups = []

    def visit(n, parent):
        ks = elems(n)
        # 1) 라벨 뒤에 비어 있는 상자(입력칸) 또는 안내 문구(…을 입력하세요)가 오는 짝
        for i, k in enumerate(ks):
            if k.tag not in ('div', 'p', 'span', 'dt', 'label'): continue
            t = clean(text_of(k))
            if not t or len(t) > 12 or has_img(k): continue
            kind = _field_kind(t)
            if not kind: continue
            if i + 1 < len(ks) and ks[i + 1].tag in ('div', 'p', 'span', 'dd') and not has_content(ks[i + 1]) and not ks[i + 1].get('role'):
                tgt = ks[i + 1]; typ, name = kind
                tgt.kids = [_input_for(typ, name, t + ' 입력', '', used)]; tgt.add_class('pg-wrap')
                groups.append(n); stats['field'] = stats.get('field', 0) + 1
        # 2) 안내 문구 자체가 입력칸인 경우
        for k in ks:
            if k.tag in ('p', 'span') and not has_img(k) and not k.get('role'):
                t = clean(text_of(k))
                if t and len(t) <= 30 and PLACEHOLDER.search(t) and len(k.kids) == 1:
                    kind = _field_kind(t) or ('text', 'field')
                    typ, name = kind
                    new = _input_for(typ, name, t, ' '.join(k.classes()), used)
                    k.tag = new.tag; k.attrs = new.attrs; k.kids = new.kids; k.selfclose = new.selfclose
                    if k.tag == 'input': k.kids = []
                    groups.append(n); stats['field'] = stats.get('field', 0) + 1
        # 3) 제출 링크
        if n.tag == 'a' and n.get('href') in ('#', '', None):
            t = clean(text_of(n))
            if SUBMIT.match(t):
                n.set('role', 'button'); n.set('data-submit', '1'); stats['submit'] = stats.get('submit', 0) + 1
        # 4) 게시판 표 구조
        if len(ks) >= 2:
            head = ks[0]
            hs = [clean(text_of(c)) for c in elems(head)]
            if sum(1 for h in hs if h in BOARD_HEAD) >= 3:
                n.set('role', 'table'); head.set('role', 'row')
                for c in elems(head): c.set('role', 'columnheader')
                for r_ in ks[1:]:
                    r_.set('role', 'row')
                    for c in elems(r_): c.set('role', 'cell')
                stats['board'] = stats.get('board', 0) + 1

    walk(root, visit)
    # 폼으로 묶기: 입력칸이 있는 가장 바깥 묶음(div)을 <form> 으로 (폼 안에 폼은 만들지 않는다)
    gid = {id(g) for g in groups}

    def wrap(n, parent, in_form=False):
        if not in_form and id(n) in gid and n.tag == 'div':
            n.tag = 'form'; n.set('action', '#'); n.set('method', 'post'); in_form = True
        for k in elems(n): wrap(k, n, in_form or n.tag == 'form')
    wrap(root, None)
    # 제출 링크: 폼 안에 있으면 <button type="submit">, 밖이면 role=button 만 남긴다
    def fin(n, parent, in_form=False):
        inf = in_form or n.tag == 'form'
        if n.tag == 'a' and n.get('data-submit'):
            n.attrs = [a_ for a_ in n.attrs if a_[0] != 'data-submit']
            if in_form:
                n.tag = 'button'; n.attrs = [a_ for a_ in n.attrs if a_[0] not in ('href', 'role')] + [['type', 'submit']]; n.add_class('pg-submit'); stats['button'] = stats.get('button', 0) + 1
        for k in elems(n): fin(k, n, inf)
    fin(root, None)


def _desc_all(n): return list(_desc(n))


def has_img(n): return any(isinstance(k, N) and k.tag == 'img' for k in [n] + list(_desc(n)))


FORM_CSS = ('.pg-field{display:block;width:100%;height:100%;box-sizing:border-box;border:0;background:transparent;outline:0;padding:0;margin:0;font:inherit;color:inherit;resize:none}\n'
            'input.pg-field::placeholder,textarea.pg-field::placeholder{color:inherit;opacity:.7}\n'
            '.pg-wrap > .pg-field{position:relative}\n')


def guess_title(main_html, title):
    """PSD 파일 이름이 main·index 처럼 사이트 이름으로 쓸 수 없으면 본문의 첫 제목을 쓴다(메타·로고 대체 텍스트용)."""
    if not re.fullmatch(r'[A-Za-z0-9_\- ]{1,10}', title or ''): return title
    found = []
    walk(parse(main_html), lambda n, p: found.append(clean(text_of(n))) if n.tag in ('h1', 'h2') and clean(text_of(n)) else None)
    t = found[0] if found else title
    return t if len(t) <= 40 else t[:38].rstrip() + '…'


def enhance(parts_html, ctx, opts=None):
    """parts_html: {'main','header','footer','quick'} → 같은 키의 새 HTML, 통계, 추가 CSS, head 에 넣을 메타.
    모든 처리는 실패해도 원본을 그대로 돌려준다(변환 자체는 절대 막지 않는다)."""
    o = dict(OPTS_DEFAULT); o.update(opts or {})
    stats = {}; out = {}; css = ''; meta = ''
    try: ctx = dict(ctx, title=guess_title(parts_html.get('main', ''), ctx.get('title', '')))
    except Exception: pass
    for key, src in parts_html.items():
        if not src: out[key] = src; continue
        try:
            root = parse(src)
            if o['repeat'] and key == 'main': repeat(root, stats); semantic_text(root, stats)
            if o['forms'] and key == 'main': forms(root, stats)
            if o['a11y']: a11y(root, dict(ctx, lazy=(key in ('main', 'footer', 'quick'))), stats)
            out[key] = dump(root)
        except Exception as e:   # 방어: 어떤 이유로든 실패하면 원본 유지
            out[key] = src; stats.setdefault('errors', []).append(f'{key}: {e}')
    if o['forms'] and (stats.get('field') or stats.get('button')): css += FORM_CSS
    if o['a11y']:
        css += SKIP_CSS
        try: meta, desc = seo_meta(out.get('main', ''), ctx); stats['description'] = desc
        except Exception as e: stats.setdefault('errors', []).append(f'seo: {e}')
    return out, stats, css, meta
