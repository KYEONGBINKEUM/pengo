"""구조화 변환 v2: PSD 레이어 → 시맨틱 HTML + 공통 스타일을 묶은 CSS (통이미지 방식 아님).

회사 코딩 예시(test.zip)를 따르는 규칙
- 태그: header#header / main#content / footer#footer, 첫 섹션은 #mVisual, 이후 #sec1, #sec2 ...
- 좌우 구성: 둘이면 .l_cont .r_cont, 셋이면 .l_cont .c_cont .r_cont
- 글자만 세로로 쌓인 묶음은 .m_txt(섹션 최상위) / .txt(카드 안), 같은 스타일은 .m_txt > h3 처럼 한 번만 정의
- 작은 버튼(도형 배경 + 글자 1개)은 a.more (아이콘형은 a.btn), 같은 스타일은 한 번만 정의
- 같은 모양 카드가 3개 이상 가로로 나열되면 ul.list > li
- 이미지는 요소마다 <img>, 도형은 CSS, 배치는 flex + gap/margin (겹치는 요소만 absolute)
- 오른쪽 고정 퀵메뉴는 aside#quick (position:fixed)
"""
import html, math, re, statistics
from collections import OrderedDict, Counter
from psd_tools.constants import Tag

# 회사 기본 규칙(이름·폭). 설정(pengo-rules.json)으로 바꿀 수 있다.
DEFAULT_CONV = {
    'inner': 1400, 'wide': 1600,
    'header_id': 'header', 'footer_id': 'footer', 'content_id': 'content', 'quick_id': 'quick',
    'visual_id': 'mVisual', 'section_prefix': 'sec',
    'box_class': 'inner', 'wide_class': 'w-inner',
    'left': 'l_cont', 'center': 'c_cont', 'right': 'r_cont',
    'text_top': 'm_txt', 'text_card': 'txt',
    'image_path': '/images/',
}
CONV = dict(DEFAULT_CONV)
INNER, WIDE = 1400, 1600
HID, FID, CID, QID, VID, SPFX, BCLS, WCLS, LC, CC, RC, TTOP, TCARD, IMGP = ('header', 'footer', 'content', 'quick', 'mVisual', 'sec', 'inner', 'w-inner', 'l_cont', 'c_cont', 'r_cont', 'm_txt', 'txt', '/images/')
AUTO = {'inner': True, 'wide': True}   # 'auto' 로 지정하면 PSD 에서 폭을 알아낸다
_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')


def set_conv(d=None):
    """사용자 규칙을 적용한다. 값이 비었거나 형식이 틀리면 기본값을 쓴다. 반환: 경고 목록"""
    global INNER, WIDE, HID, FID, CID, QID, VID, SPFX, BCLS, WCLS, LC, CC, RC, TTOP, TCARD, IMGP
    warn = []
    CONV.clear(); CONV.update(DEFAULT_CONV); AUTO['inner'] = AUTO['wide'] = True   # 폭은 기본이 자동 인식(숫자를 적으면 고정)
    for k, v in (d or {}).items():
        if k not in DEFAULT_CONV: continue
        if k in ('inner', 'wide'):
            if str(v).strip().lower() == 'auto':
                continue
            try:
                v = int(v)
                if not 300 <= v <= 4000: raise ValueError
            except Exception:
                warn.append(f'{k}: 300~4000 사이 숫자(또는 auto)여야 합니다. 자동 인식을 씁니다'); continue
            AUTO[k] = False
        elif k == 'image_path':
            v = str(v).strip()
            if not v: continue
            if not v.endswith('/'): v += '/'
        else:
            v = str(v).strip()
            if not _NAME.match(v):
                warn.append(f'{k}: 영문으로 시작하는 영문·숫자·_·- 만 쓸 수 있습니다("{v}"). 기본값을 씁니다'); continue
        CONV[k] = v
    if CONV['inner'] >= CONV['wide']:
        warn.append('inner 는 wide 보다 작아야 합니다. 기본값을 씁니다'); CONV['inner'], CONV['wide'] = DEFAULT_CONV['inner'], DEFAULT_CONV['wide']
    c = CONV
    INNER, WIDE = c['inner'], c['wide']
    HID, FID, CID, QID, VID, SPFX = c['header_id'], c['footer_id'], c['content_id'], c['quick_id'], c['visual_id'], c['section_prefix']
    BCLS, WCLS, LC, CC, RC, TTOP, TCARD, IMGP = c['box_class'], c['wide_class'], c['left'], c['center'], c['right'], c['text_top'], c['text_card'], c['image_path']
    return warn
import os as _os
_OPT = _os.environ.get('PSDPUB_OPT', 'snap,merge,line')  # 시험용 스위치(기본: 모두 켬)


def hexc(c): return '#%02x%02x%02x' % tuple(max(0, min(255, round(v))) for v in c)
_SC = [1]  # PSD 배율(2x 시안이면 2): 모든 CSS 길이를 이 값으로 나눠 1배 시안과 같은 코드가 나오게 한다


def px(v):
    v = v / _SC[0]
    return ('%.1f' % v).rstrip('0').rstrip('.') + 'px'


class Part:  # 렌더 결과 한 조각
    def __init__(self, html_, bbox, sel='', kind='box', rec=None, tag=None):
        self.html, self.bbox, self.sel, self.kind, self.rec, self.tag = html_, bbox, sel, kind, rec, tag


BLEND_CSS = {'MULTIPLY': 'multiply', 'SCREEN': 'screen', 'OVERLAY': 'overlay', 'SOFT_LIGHT': 'soft-light', 'HARD_LIGHT': 'hard-light', 'COLOR_DODGE': 'color-dodge',
             'COLOR_BURN': 'color-burn', 'DARKEN': 'darken', 'LIGHTEN': 'lighten', 'DIFFERENCE': 'difference', 'EXCLUSION': 'exclusion', 'LINEAR_BURN': 'multiply', 'LINEAR_DODGE': 'plus-lighter'}

class Semantic:
    def __init__(self, r, only=None, quality='lossless', scale=1, img_scale=1, css_round='tidy'):
        self.r, self.psd = r, r.psd
        self.css_round = css_round  # 'tidy': 간격 5px·2px 단위 / 'exact': 소수점만 정수로
        self.emit = lambda pct, msg: None  # 진행 상황 알림(publisher가 연결)
        self.S = max(1, int(scale)); _SC[0] = self.S
        self.SEMP = re.compile(r'^\.(' + re.escape(TTOP) + '|' + re.escape(TCARD) + r'|gnb|nav)\d*$')
        self.quality, self.img_scale = quality, max(1, int(img_scale))
        self.W, self.H = self.psd.width, self.psd.height
        self.only = only or []
        self.idx = {id(l): i for i, l in enumerate(r.layers)}
        self.elems = []  # (CSS 경로, PSD 영역, 글자/버튼 rec): 불일치 보고서에서 '어느 CSS를 고칠지' 알려주기 위한 기록
        self.lifted = set()  # 묶음 밖으로 꺼낸 구분선 레이어
        self.hidden = set()  # 변환에서 제외할 레이어(헤더 하단선 등)
        self.loose_bg = {}   # 그룹 밖(루트)에 있는 전체 폭 배경 레이어 → 섹션
        self._align = {}
        self.fonts_used = {}  # 사용한 PSD 글꼴 → 구글 폰트 이름(없으면 None)
        self.img_cnt = {}  # (섹션 id, 'img'|'bg') → 저장한 개수 (파일 이름 번호용)
        self.cur_cw = 0  # 현재 섹션 컨테이너 폭(PSD px)
        self.sec_ranges = {}  # 섹션 id → (PSD y시작, y끝, PSD 그룹 이름) : 불일치 보고서용
        self.sec_names = {'header': 'header', 'footer': 'footer', 'quick': 'quick (오른쪽 고정 메뉴)'}
        self.rules = OrderedDict(); self.glob = OrderedDict(); self.names = {}; self.notes = []; self.sec = 'x'
        self.texts = []; self.btns = []; self.card_depth = 0
        # 클리핑 체인: 기준 레이어 id → 그 위에 클리핑된 레이어들
        self.chains = {}; self.clipped = set()
        for grp in [self.psd] + [l for l in self.psd.descendants() if l.is_group()]:
            sibs = list(grp)
            for i, c in enumerate(sibs):
                if c.clipping and i > 0:
                    j = i - 1
                    while j > 0 and sibs[j].clipping: j -= 1
                    self.chains.setdefault(id(sibs[j]), []).append(c); self.clipped.add(id(c))

    # ---------- 공통 ----------
    def vis(self, l):
        if not (l.is_visible() and l.width > 0 and l.height > 0) or id(l) in self.hidden: return False
        if not l.is_group():   # 캔버스 밖으로 완전히 나간 레이어(작업 중 남은 찌꺼기 등)는 무시
            b = l.bbox
            if b[2] <= 0 or b[0] >= self.W or b[3] <= 0 or b[1] >= self.H: return False
        return True
    def rid(self, l): return f'L{self.idx[id(l)]:04d}'

    def name(self, base, path):
        key = ('>'.join(path), base); n = self.names.get(key, 0) + 1; self.names[key] = n
        return base if n == 1 else f'{base}{n}'

    def reg(self, path, bbox, rec=None):
        self.elems.append((tuple(path), tuple(bbox), rec))

    def rule(self, path, decls):
        if isinstance(decls, str): decls = [decls]
        self.rules.setdefault(tuple(path), []).extend(decls)

    def geom(self, l):
        """도형의 실제 기하. PSD bbox는 도형 둘레 번짐 여백(1px)을 포함하므로 벡터 원본값으로 보정한다."""
        x0, y0, x1, y1 = l.bbox
        if l.kind != 'shape': return (x0, y0, x1, y1)
        try:
            for o in (l.origination or []):
                if type(o).__name__ in ('Rectangle', 'RoundedRectangle', 'Ellipse'):
                    b = o.bbox
                    if all(abs(a - c) <= 2 * self.S for a, c in zip(b, (x0, y0, x1, y1))): return tuple(b)
        except Exception:
            pass
        w, h = x1 - x0, y1 - y0
        S = self.S
        if min(w, h) <= 6 * S:  # 선(스트로크): CSS 1px(= PSD S px), 번짐 여백을 뺀 위치
            if w >= h: m = y0 + h // 2 - (S - 1); return (x0 + 1, m, x1 - 1, m + S)
            m = x0 + w // 2 - (S - 1); return (m, y0 + 1, m + S, y1 - 1)
        return (x0 + 1, y0 + 1, x1 - 1, y1 - 1)

    def box_of(self, g):
        """그룹의 실제 상자: 배경 도형이 있으면 그 도형의 실제 기하."""
        if any(id(c) in self.lifted or not self.vis(c) for c in g):   # 위로 올려 보낸 구분선·안 보이는/캔버스 밖 레이어는 이 묶음의 크기에서 뺀다
            bx = [self.box_of(c) if c.is_group() else tuple(c.bbox) for c in g if self.vis(c) and id(c) not in self.lifted]
            if bx: return (min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx))
        bg = next((c for c in g if self.vis(c) and c.kind == 'shape' and all(abs(a - b) <= 3 * self.S for a, b in zip(c.bbox, g.bbox))), None)
        return self.geom(bg) if bg is not None else tuple(g.bbox)

    def merge_blend_cards(self, its):
        """도형 위에 '밝게(Lighten)/스크린' 혼합 모드로 올린 사진(도형 모양으로 사진을 오려 보이게 하는 기법)은
        클리핑과 같은 효과이므로, 도형+사진(+그 위의 곱하기 도형)을 합성해 모서리까지 오려진 이미지 한 장으로 만든다."""
        bmode = lambda l: str(getattr(l, 'blend_mode', '')).split('.')[-1]
        cons = set(); S3 = 3 * self.S
        for it in list(its):
            l = it['layer']
            if l.is_group() or l.kind not in ('pixel', 'smartobject') or l.clipping or bmode(l) not in ('LIGHTEN', 'SCREEN') or it.get('merged'): continue
            lx0, ly0, lx1, ly1 = l.bbox
            cl, cr = lx0 <= 0, lx1 >= self.W   # 캔버스 가장자리에서 잘린 사진은 그쪽 경계를 따지지 않는다
            inside = lambda b: (cl or lx0 - S3 <= b[0]) and (cr or b[2] <= lx1 + S3) and ly0 - S3 <= b[1] and b[3] <= ly1 + S3 and b[0] < lx1 and b[2] > lx0
            cand = [j for j in its if not j['layer'].is_group() and j['layer'].kind == 'shape' and id(j['layer']) not in cons
                    and self.idx[id(j['layer'])] < self.idx[id(l)] and inside(j['bbox'])]
            if not cand: continue
            sh = max(cand, key=lambda j: self.idx[id(j['layer'])]); shb = sh['bbox']
            keep = {id(sh['layer']), id(l), id(l.parent)}; used = [sh]
            for j in its:
                jl = j['layer']
                if (not jl.is_group() and jl.kind == 'shape' and id(jl) not in cons and jl is not sh['layer'] and self.idx[id(jl)] > self.idx[id(l)] and bmode(jl) == 'MULTIPLY'
                        and all(abs(a - b) <= S3 for a, b in zip(j['bbox'], shb))):
                    keep.add(id(jl)); used.append(j)
            vb = (max(0, int(round(shb[0]))), int(round(shb[1])), min(self.W, int(round(shb[2]))), int(round(shb[3])))   # 캔버스 밖은 합성 시 검게 채워지므로 안쪽만
            try: im = l.parent.composite(viewport=vb, force=True, layer_filter=lambda x: id(x) in keep)
            except Exception: im = None
            if im is None: continue
            it['merged'] = self.save_img(im, 'img', self.rid(l)); it['bbox'] = (vb[0], vb[1], vb[2], vb[3])
            cons |= {id(u['layer']) for u in used}
        return [i for i in its if id(i['layer']) not in cons]

    def lift_lines(self, its):
        """묶음 안에 묶음 폭을 거의 다 채우는 가로 구분선이 들어 있으면, 선을 묶음 밖(같은 단계)으로 꺼낸다.
        선 때문에 묶음이 옆 요소와 겹쳐 보여 absolute 배치가 되는 것을 막고, 선은 이웃 요소의 border 로 바뀐다."""
        out = []
        for it in its:
            out.append(it); l = it['layer']
            if not l.is_group() or id(l) in self.chains: continue
            kids = [c for c in l if self.vis(c)]
            for c in kids:
                if c.kind != 'shape' or id(c) in self.chains or id(c) in self.lifted: continue
                gx0, gy0, gx1, gy1 = self.geom(c); th, w = gy1 - gy0, gx1 - gx0
                if th > 4 * self.S or w < 4 * th or w < 0.7 * (l.bbox[2] - l.bbox[0]): continue
                rest = [k for k in kids if k is not c]
                if not rest: continue
                rw = max(k.bbox[2] for k in rest) - min(k.bbox[0] for k in rest)
                if rw >= 0.85 * w: continue
                self.lifted.add(id(c)); it['bbox'] = self.box_of(l)
                li = self.item(c)
                if li: out.append(li)
        return out

    def set_sels(self, parts, shift=0):
        """글자/버튼은 클래스 없이 nth-child로 지정(공통 스타일은 태그 선택자로 묶음)."""
        for i, q in enumerate(parts):
            if q.kind in ('text', 'btn'):
                q.sel = f'{q.tag}:nth-child({i + 1 + shift})'
                if q.rec is not None: q.rec['sel'] = q.sel

    # ---------- 도형/텍스트 정보 ----------
    def shape_style(self, l):
        d = []
        try:
            c = l.tagged_blocks.get_data(Tag.SOLID_COLOR_SHEET_SETTING)[b'Clr ']
            col = hexc((c[b'Rd  '], c[b'Grn '], c[b'Bl  ']))
            op = l.opacity / 255
            d.append(f'background:{col}' if op >= 0.99 else 'background:rgba(%d,%d,%d,%g)' % (int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16), round(op, 2)))
        except Exception:
            try:  # 단색 채움 정보가 없고 선(스트로크)만 있는 도형: 채움이 켜져 있으면 선 색을 채움색으로 사용
                sd = l.tagged_blocks.get_data(Tag.VECTOR_STROKE_DATA)
                c = l.tagged_blocks.get_data(Tag.VECTOR_STROKE_CONTENT_DATA)[b'Clr ']
                if sd.get(b'fillEnabled'): d.append('background:' + hexc((c[b'Rd  '], c[b'Grn '], c[b'Bl  '])))
            except Exception:
                self.notes.append(f'{self.rid(l)}: 도형 색상(그라데이션/패턴 등)을 읽지 못해 배경색을 넣지 않았습니다.')
        try:  # 도형 테두리: strokeStyleContent 색 + 선 두께
            sd = l.tagged_blocks.get_data(Tag.VECTOR_STROKE_DATA)
            if sd.get(b'strokeEnabled'):
                sc = sd[b'strokeStyleContent'][b'Clr ']
                d.append(f'border:{px(float(sd.get(b"strokeStyleLineWidth", 1.0)))} solid ' + hexc((sc[b'Rd  '], sc[b'Grn '], sc[b'Bl  '])))
        except Exception:
            pass
        try:
            for o in (l.origination or []):
                t = type(o).__name__
                if t == 'Ellipse': d.append('border-radius:50%')
                elif t == 'RoundedRectangle' and o.radii:
                    v = [o.radii.get(k) for k in (b'topLeft', b'topRight', b'bottomRight', b'bottomLeft')]
                    if all(x is not None for x in v) and max(v) > 0:
                        d.append('border-radius:' + (px(v[0]) if len(set(v)) == 1 else ' '.join(px(x) for x in v)))
        except Exception:
            pass
        bm = BLEND_CSS.get(str(getattr(l, 'blend_mode', '')).split('.')[-1])   # 포토샵 혼합 모드(곱하기 등) → mix-blend-mode
        if bm: d.append('mix-blend-mode:' + bm)
        return d

    def text_info(self, l):
        row = self.r.rows[self.rid(l)]
        runs = row.get('runs') or []
        if runs and not row.get('_lh_fixed'):   # 한 줄짜리 글자는 PSD 의 큰 줄간격(leading)이 의미 없으므로 줄 높이를 글자 크기 기준으로 제한
            row['_lh_fixed'] = True
            if row['text'].strip('\n').count('\n') == 0:
                for ru in runs: ru['line_height_px'] = min(ru['line_height_px'], max(ru['font_size_px'] * 2.2, 1))
        return row, runs

    def text_bbox(self, l):
        """글자 상자: PSD 잉크 영역 → CSS 줄 상자(줄 높이 기준 중앙 정렬)로 보정."""
        row, runs = self.text_info(l)
        x0, y0, x1, y1 = l.bbox
        if not runs: return (x0, y0, x1, y1)
        lh = runs[0]['line_height_px']; n = row['text'].strip('\n').count('\n') + 1
        cy = (y0 + y1) / 2
        return (x0, cy - n * lh / 2, x1, cy + n * lh / 2)

    def tag_for(self, l):
        row, runs = self.text_info(l)
        if not runs: return 'p'
        if self.sec == 'header' or len(row['text'].strip()) <= 2: return 'p'
        s = round(max(r['font_size_px'] for r in runs))
        if s >= 40: return 'h2'
        if s >= 28: return 'h3'
        if s >= 18 and any(r['weight'] >= 500 for r in runs): return 'h4'
        return 'p'

    def rotation(self, l):
        """글자 레이어의 회전각(도). '←'를 180° 돌려 '→'로 쓰는 경우 등."""
        t = self.r.rows[self.rid(l)].get('transform')
        if not t or len(t) < 2: return 0
        deg = math.degrees(math.atan2(t[1], t[0]))
        for k in (0, 90, -90, 180, -180):
            if abs(deg - k) < 1.5: return 180 if abs(k) == 180 else k
        return round(deg, 1)

    def text_extra(self, l):
        """공통 스타일에 섞지 않고 그 글자에만 적용할 선언: 여러 줄 문단 정렬(오른쪽·가운데)"""
        row = self.text_info(l)[0]
        try:  # 문단 정렬 1=오른쪽, 2=가운데
            j = (row.get('paragraphs') or {})['RunArray'][0]['ParagraphSheet']['Properties'].get('Justification')
            if '\n' in row['text'].strip() and j in (1, 2):
                px_al = self.align_by_pixels(l)   # 파일 속성이 실제 모양과 다른 경우가 있어 줄 끝 위치로 한 번 더 확인
                if px_al == 'left': return []
                if px_al in ('right', 'center'): return ['text-align:' + px_al]
                return ['text-align:' + ('right' if j == 1 else 'center')]
        except Exception:
            pass
        return []

    def align_by_pixels(self, l):
        """여러 줄 글자의 실제 정렬: 줄마다 왼쪽 끝/오른쪽 끝/가운데가 같은 곳에 맞는지 픽셀로 판정. 판정 불가면 None."""
        k = id(l)
        if k in self._align: return self._align[k]
        res = None
        try:
            import numpy as np
            im = l.composite(force=True)
            if im is not None:
                a = np.array(im.convert('RGBA').getchannel('A')) > 40
                rows = a.any(axis=1); bands = []; st = None
                for y, v in enumerate(rows):
                    if v and st is None: st = y
                    if not v and st is not None: bands.append((st, y)); st = None
                if st is not None: bands.append((st, len(rows)))
                ext = []
                for y0, y1 in bands:
                    xs = np.where(a[y0:y1].any(axis=0))[0]
                    if len(xs) and y1 - y0 >= 4: ext.append((int(xs[0]), int(xs[-1])))
                if len(ext) >= 2:
                    tol = 3 * self.S
                    sl = max(e[0] for e in ext) - min(e[0] for e in ext)
                    sr = max(e[1] for e in ext) - min(e[1] for e in ext)
                    sc = max((e[0] + e[1]) / 2 for e in ext) - min((e[0] + e[1]) / 2 for e in ext)
                    if sl <= tol and sl <= sr: res = 'left'
                    elif sr <= tol and sr < sl: res = 'right'
                    elif sc <= tol: res = 'center'
        except Exception:
            res = None
        self._align[k] = res
        return res

    KNOWN_FONTS = {'NotoSerifKR': ("'Noto Serif KR',serif", 'Noto+Serif+KR'), 'NotoSansKR': ("'Noto Sans KR',sans-serif", 'Noto+Sans+KR'),
                   'SUIT': ("'SUIT',sans-serif", None), 'Roboto': ("'Roboto',sans-serif", 'Roboto')}

    def font_decl(self, fname):
        """PSD 글꼴 이름 → font-family. 기본 글꼴(Pretendard)은 default.css 에 있으므로 출력하지 않는다."""
        fam = (fname or '').split('-')[0]
        if fam in ('', 'Pretendard'): return None
        if fam in self.KNOWN_FONTS: css, g = self.KNOWN_FONTS[fam]
        else:
            name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', fam)
            css, g = f"'{name}',{'serif' if re.search('Serif|Myeongjo|Batang', fam) else 'sans-serif'}", None
        self.fonts_used[fam] = g
        return 'font-family:' + css

    def text_decls(self, l):
        row, runs = self.text_info(l)
        if not runs: return [], None
        base = max(runs, key=lambda r: len(r['text'].strip()))
        fs = base['font_size_px']
        d = [f'font-size:{int(round(fs / _SC[0]))}px', f'font-weight:{base["weight"]}', f'color:{base["color"]}',
             f'line-height:{round(base["line_height_px"] / fs, 1):g}em', 'white-space:nowrap']
        fam = self.font_decl(base['font'])
        if fam: d.insert(1, fam)   # PSD 글꼴이 기본(Pretendard)이 아니면 font-family 출력
        if abs(base['letter_spacing_px']) > 0.05: d.append(f'letter-spacing:{round(base["letter_spacing_px"] / fs, 2):g}em')
        if l.opacity < 254: d.append(f'opacity:{round(l.opacity / 255, 2):g}')
        rot = self.rotation(l)
        if rot: d.append(f'transform:rotate({rot}deg)')
        rs = base.get('raw_style') or {}
        if rs.get('Underline'): d.append('text-decoration:underline'); d.append('text-underline-offset:' + px(3 * self.S))
        if rs.get('Strikethrough'): d.append('text-decoration:line-through')
        return d, base

    SPACE_EM = 0.24 # 공백 한 칸의 폭(em). 2칸 이상 띄운 곳은 span으로 나누고 간격을 CSS margin으로 옮긴다.

    def text_inner(self, l):
        """(html, gaps) 반환. gaps = [(span 순번, 간격 px), ...] — 공백으로 띄운 구간을 span 단위로 분리."""
        row, runs = self.text_info(l)
        txt = row['text'].strip('\n')
        if not runs: return html.escape(txt).replace('\n', '<br>'), []
        base = max(runs, key=lambda r: len(r['text'].strip()))
        pieces = []  # ('t', 글자, run) | ('g', 칸수, run) | ('br',)
        for k, ru in enumerate(runs):
            raw = ru['text'].rstrip('\n') if k == len(runs) - 1 else ru['text']  # 중간 구간의 줄바꿈은 유지
            for seg in re.split(r'(\n)', raw):
                if seg == '\n': pieces.append(('br',)); continue
                for sub in re.split(r'( {2,})', seg):
                    if not sub: continue
                    pieces.append(('g', len(sub), ru) if sub.strip(' ') == '' and len(sub) >= 2 else ('t', sub, ru))

        def rt(t, ru):
            t = html.escape(t)
            diff = (ru['color'] != base['color'], ru['weight'] != base['weight'], round(ru['font_size_px']) != round(base['font_size_px']))
            if not any(diff): return t
            st = []
            if diff[0]: st.append(f'color:{ru["color"]}')
            if diff[1]: st.append(f'font-weight:{ru["weight"]}')
            if diff[2]: st.append(f'font-size:{int(round(ru["font_size_px"] / _SC[0]))}px')
            return f'<b style="{";".join(st)}">{t}</b>'  # 스타일만 다른 구간: span(공백 구간 전용)과 구분해 <b> 사용
        lines = [[]]
        for p in pieces:
            if p[0] == 'br': lines.append([])
            else: lines[-1].append(p)
        out, gaps, nspan = [], [], 0
        for ln in lines:
            while ln and ln[0][0] == 'g': ln.pop(0)
            while ln and ln[-1][0] == 'g': ln.pop()
            if not any(p[0] == 'g' for p in ln):
                out.append(''.join(rt(p[1], p[2]) for p in ln)); continue
            groups = [[]]
            for p in ln:
                if p[0] == 'g':
                    ru = p[2]; groups.append([]); nspan += 1
                    gaps.append((nspan + 1, round(p[1] * (self.SPACE_EM * ru['font_size_px'] + ru['letter_spacing_px']), 1)))
                else: groups[-1].append(p)
            nspan += 1  # 첫 span
            out.append(''.join('<span>' + ''.join(rt(q[1], q[2]) for q in g) + '</span>' for g in groups))
        return '<br>'.join(out), gaps

    # ---------- 이미지 ----------
    def img_name(self, kind):
        """파일 이름: 일반 이미지는 sec1_img1, sec1_img2 …  배경은 sec1_bg, sec1_bg2 … (섹션 id 기준)"""
        key = (self.sec, kind)
        n = self.img_cnt.get(key, 0) + 1
        self.img_cnt[key] = n
        return f'{self.sec}_img{n}' if kind == 'img' else f'{self.sec}_bg' + ('' if n == 1 else str(n))

    def save_img(self, image, kind, layer=None):
        """이미지 저장. quality: lossless(WebP 무손실, 기본·최대화질) / png(PNG 무손실) / high(WebP 95) / normal(WebP 85).
        img_scale>1 이면 가로·세로를 배수만큼 확대 저장(레티나용). CSS 크기는 그대로라 코드는 1배와 같다."""
        from PIL import Image
        d = self.out / 'images' / 'main'; d.mkdir(parents=True, exist_ok=True)
        base = self.img_name(kind)
        if self.img_scale > 1:
            k = self.img_scale; image = image.resize((image.width * k, image.height * k), Image.LANCZOS)
        if self.quality == 'png':
            ext, kw, fmt = 'png', {'optimize': True}, 'PNG'
        else:
            ext, fmt = 'webp', 'WEBP'
            kw = {'lossless': True, 'quality': 100, 'method': 4} if self.quality == 'lossless' else {'quality': 95 if self.quality == 'high' else 85, 'method': 6}  # 무손실은 method 4: method 6보다 10배 빠르고 용량 차이 1% 미만
        if image.mode not in ('RGB', 'RGBA'): image = image.convert('RGBA')
        if fmt == 'WEBP' and max(image.size) > 16383:  # WebP 크기 한계 → PNG로 대체
            ext, fmt, kw = 'png', 'PNG', {'optimize': True}
        rel = f'images/main/{base}.{ext}'
        self.emit(-1, f'이미지 저장 중: {base}.{ext}')
        image.save(d / f'{base}.{ext}', fmt, **kw)
        self.r.assets.append({'layer': layer or base, 'path': rel, 'width': image.width, 'height': image.height, 'text_removed': True,
                              'quality': self.quality, 'image_scale': self.img_scale})
        return IMGP + rel[len('images/'):]   # 서브페이지에서도 불러오도록 루트 절대경로(기본 /images/…)

    def leaf_img(self, l):
        im = None
        chain = self.chains.get(id(l))
        if chain:  # 클리핑된 층(색 입히기 등)을 포함해 합성
            par = l.parent; keep = {id(par), id(l)} | {id(c) for c in chain}
            try: im = par.composite(viewport=l.bbox, force=True, layer_filter=lambda x: id(x) in keep)
            except Exception: im = None
            if im is not None: return self.save_img(im, 'img', self.rid(l))
        try:
            im = l.topil()  # 클리핑된 레이어도 자기 픽셀 그대로 추출
            if im is not None and im.convert('RGBA').getchannel('A').getextrema()[1] == 0: im = None
        except Exception:
            im = None
        if im is None: im = l.composite(force=True)
        if im is None: self.notes.append(f'{self.rid(l)} 이미지 추출 실패'); return None
        return self.save_img(im, 'img', self.rid(l))

    # ---------- 분할(XY-cut) ----------
    def item(self, l, force=False):
        if id(l) in self.clipped and l.kind != 'type' and not force: return None  # 기준 레이어와 합쳐 한 장으로 저장됨
        if l.kind == 'type': bb = self.text_bbox(l)
        elif l.kind == 'shape': bb = self.geom(l)
        elif l.is_group(): bb = self.box_of(l)
        else: bb = tuple(l.bbox)
        if l.is_group() and not [c for c in l if self.vis(c)]: return None
        return {'layer': l, 'bbox': bb}

    def split(self, items, axis):
        its = sorted(items, key=lambda i: (i['bbox'][axis], i['bbox'][axis + 2]))
        cl = [[its[0]]]; end = its[0]['bbox'][axis + 2]
        for it in its[1:]:
            if it['bbox'][axis] >= end - self.S: cl.append([it]); end = it['bbox'][axis + 2]
            else: cl[-1].append(it); end = max(end, it['bbox'][axis + 2])
        return cl

    def cut(self, items):
        if len(items) == 1: return ('leaf', items[0])
        for axis, kind in ((1, 'col'), (0, 'row')):
            cl = self.split(items, axis)
            if len(cl) > 1: return (kind, [self.cut(c) for c in cl])
        return ('stack', sorted(items, key=lambda i: self.idx[id(i['layer'])]))  # 아래 레이어(번호 작은 것)를 먼저 그려 위에 쌓음

    # ---------- 렌더 ----------
    def render(self, tree, path, role=None, li=False, bare=False):
        kind = tree[0]
        if kind == 'leaf': return self.render_item(tree[1], path, role, li, bare)
        if kind == 'stack': return self.render_stack(tree[1], path, role)
        return self.render_seq(kind, tree[1], path, role)

    def has_rmask(self, l):
        try: return bool(l.has_mask() and not l.mask.disabled)
        except Exception: return False

    def render_item(self, it, path, role=None, li=False, bare=False):
        l = it['layer']
        if it.get('merged'):
            x0, y0, x1, y1 = it['bbox']; cls = self.name('img', path)
            self.rule(path + ['.' + cls], ['flex-shrink:0'])
            self.rule(path + ['.' + cls, '.pic'], ['display:block', 'width:' + px(x1 - x0), 'height:auto', 'max-width:100%'])
            self.reg(path + ['.' + cls], it['bbox'])
            return Part(f'<div class="{cls}"><img class="pic" src="{it["merged"]}" alt=""></div>', tuple(it['bbox']), '.' + cls, 'img')
        if l.kind == 'type': return self.render_text(l, it['bbox'], path, li, bare)
        if l.is_group(): return self.render_group(l, path, role)
        x0, y0, x1, y1 = l.bbox
        if l.kind == 'shape' and id(l) not in self.chains and self.has_rmask(l):
            # 레이어 마스크(그라데이션 등)가 걸린 도형: CSS 로는 표현할 수 없으므로 마스크·불투명도를 적용한 이미지로 저장(혼합 모드는 CSS로)
            try: im = l.composite(force=True)
            except Exception: im = None
            if im is not None:
                src = self.save_img(im, 'img', self.rid(l)); cls = self.name('img', path)
                bm = BLEND_CSS.get(str(getattr(l, 'blend_mode', '')).split('.')[-1])
                self.rule(path + ['.' + cls], ['flex-shrink:0'] + ([f'mix-blend-mode:{bm}'] if bm else []))
                self.rule(path + ['.' + cls, '.pic'], ['display:block', 'width:' + px(x1 - x0), 'height:auto', 'max-width:100%'])
                self.reg(path + ['.' + cls], l.bbox)
                return Part(f'<div class="{cls}"><img class="pic" src="{src}" alt=""></div>', tuple(l.bbox), '.' + cls, 'img')
        if l.kind == 'shape' and id(l) not in self.chains:
            gx0, gy0, gx1, gy1 = self.geom(l)
            cls = self.name('line' if min(gx1 - gx0, gy1 - gy0) <= 4 * self.S else 'deco', path)
            st = self.shape_style(l)
            self.rule(path + ['.' + cls], ['width:' + px(gx1 - gx0), 'height:' + px(gy1 - gy0), 'box-sizing:border-box', 'flex-shrink:0'] + st)
            self.reg(path + ['.' + cls], (gx0, gy0, gx1, gy1))
            rec = None
            bgv = [x for x in st if x.startswith('background:')]
            if cls.startswith('line') and (gx1 - gx0) >= 4 * (gy1 - gy0) and bgv and not any(x.startswith('border') for x in st):
                rec = {'hline': True, 'color': bgv[0].split(':', 1)[1].strip(), 'thick': gy1 - gy0}  # 가로선 → 나중에 이웃 요소의 border로 바꿀 수 있음
            return Part(f'<div class="{cls}"></div>', (gx0, gy0, gx1, gy1), '.' + cls, 'shape', rec)
        src = self.leaf_img(l)
        if not src: return Part('', tuple(l.bbox), '', 'empty')
        cls = self.name('img', path)
        self.rule(path + ['.' + cls], ['flex-shrink:0'] + ([] if l.opacity >= 254 else [f'opacity:{l.opacity / 255:.2f}']))
        self.rule(path + ['.' + cls, '.pic'], ['display:block', 'width:' + px(x1 - x0), 'height:auto', 'max-width:100%'])
        self.reg(path + ['.' + cls], l.bbox)
        return Part(f'<div class="{cls}"><img class="pic" src="{src}" alt=""></div>', tuple(l.bbox), '.' + cls, 'img')

    def render_text(self, l, bb, path, li=False, bare=False):
        """홀로 있는 글자는 <div class="txt"><h3>…</h3></div> 로 감싼다(#sec1 .l_cont .txt h3 형태로 스타일 지정)."""
        tag = 'li' if li else self.tag_for(l)
        d, _ = self.text_decls(l)
        wrap = not li and not bare
        if wrap: wcls = self.name(TCARD, path); tpath = list(path) + ['.' + wcls]
        else: tpath = list(path)
        rec = {'path': tpath, 'tag': tag, 'sel': tag if wrap else None, 'decls': d, 'gaps': [], 'extra': self.text_extra(l)}
        self.texts.append(rec)
        self.reg(tpath, bb, rec)
        inner, rec['gaps'] = self.text_inner(l)
        if li: inner = f'<a href="#">{inner}</a>'
        self.r.bindings.append({'layer': self.rid(l), 'role': 'semantic-text'})
        el = f'<{tag}>{inner}</{tag}>'
        if wrap:
            wattr = TCARD if wcls == TCARD else f'{TCARD} {wcls}'   # 공통 클래스(txt) + 고유 클래스(txt2): .txt h3 공통 규칙이 모두에 적용됨
            return Part(f'<div class="{wattr}">{el}</div>', bb, '.' + wcls, 'box')
        return Part(el, bb, '', 'text', rec, tag)

    def render_button(self, g, bg, text, path):
        d, base = self.text_decls(text)
        rot = self.rotation(text)
        d = [x for x in d if not x.startswith('transform')]  # 회전은 버튼 전체가 아니라 안쪽 글자에만
        gx0, gy0, gx1, gy1 = self.geom(bg); tx0, _, tx1, _ = text.bbox
        label = self.text_info(text)[0]['text'].strip()
        cls = 'btn' if len(label) <= 2 else ('badge' if (gy1 - gy0) <= 36 * self.S else 'more')
        w, h = gx1 - gx0, gy1 - gy0
        d = [x for x in d if not x.startswith('line-height')] + ['line-height:1', 'display:inline-flex', 'align-items:center', 'justify-content:center',
             'box-sizing:border-box', 'flex-shrink:0']
        if cls == 'btn':  # 아이콘형(원형·정사각): 가로·세로를 모두 고정해 찌그러지지 않게
            d += ['width:' + px(w), 'height:' + px(h), 'padding:0']
            if abs(w - h) <= 2 * self.S: d.append('aspect-ratio:1 / 1')
            else: d.append(f'aspect-ratio:{round(w)} / {round(h)}')
        else:     # 글자 버튼/배지: 높이 고정 + 가로 최소폭 고정(글자 폭이 달라져도 PSD보다 좁아지지 않게)
            pl, pr = max(0, tx0 - gx0), max(0, gx1 - tx1)
            if abs(pl - pr) <= 2 * self.S: pl = pr = (pl + pr) / 2   # 좌우가 거의 같으면 대칭으로
            d += ['height:' + px(h), 'min-width:' + px(w), f'padding:0 {px(pr)} 0 {px(pl)}']
        d += self.shape_style(bg)
        rec = {'cls': cls, 'decls': d, 'path': list(path), 'sel': None}
        self.btns.append(rec)
        self.reg(path, (gx0, gy0, gx1, gy1), rec)
        self.r.bindings.append({'layer': self.rid(text), 'role': 'semantic-button'})
        tagname = 'span' if cls == 'badge' else 'a'; extra = '' if cls == 'badge' else ' href="#"'
        inner, _ = self.text_inner(text)
        if rot: inner = f'<span style="display:inline-block;transform:rotate({rot}deg)">{inner}</span>'
        return Part(f'<{tagname} class="{cls}"{extra}>{inner}</{tagname}>', (gx0, gy0, gx1, gy1), '', 'btn', rec, tagname)

    def role_wrap(self, role, path, inner_html, bbox):
        cls = self.name(role, path)
        return cls, f'<div class="{cls}">{inner_html}</div>'

    def render_stack(self, items, path, role=None):
        ls = [i['layer'] for i in items]
        if len(ls) == 2 and sorted(l.kind for l in ls) == ['shape', 'type']:  # 도형 위에 글자 = 배지/버튼
            sh = next(l for l in ls if l.kind == 'shape'); tx = next(l for l in ls if l.kind == 'type')
            if tx.bbox[0] >= sh.bbox[0] - 2 * self.S and tx.bbox[2] <= sh.bbox[2] + 2 * self.S and sh.width <= 320 * self.S and sh.height <= 80 * self.S and id(sh) not in self.chains:
                return self.render_button(None, sh, tx, path)
        cls = self.name(role or 'box', path); p = path + ['.' + cls]
        parts = [q for q in (self.render(('leaf', it), p) for it in items) if q.html]
        self.set_sels(parts)
        bb = (min(q.bbox[0] for q in parts), min(q.bbox[1] for q in parts), max(q.bbox[2] for q in parts), max(q.bbox[3] for q in parts))
        self.reg(p, bb)
        self.rule(p, ['position:relative', 'width:' + px(bb[2] - bb[0]), 'height:' + px(bb[3] - bb[1]), 'flex-shrink:0'])
        for q in parts:
            self.rule(p + [q.sel], ['position:absolute', 'left:' + px(q.bbox[0] - bb[0]), 'top:' + px(q.bbox[1] - bb[1])])
        self.notes.append(f'{" > ".join(p)}: 서로 겹치는 요소라 absolute로 배치했습니다(겹침 구조는 자동 판별 한계).')
        return Part(f'<div class="{cls}">' + ''.join(q.html for q in parts) + '</div>', bb, '.' + cls)

    def is_card(self, s):
        if s[0] != 'leaf' or not s[1]['layer'].is_group(): return False
        g = s[1]['layer']
        return any(c.kind == 'shape' and self.vis(c) and all(abs(a - b) <= 3 * self.S for a, b in zip(c.bbox, g.bbox)) for c in g)

    def group_text_runs(self, subs):
        """세로로 이어진 글자 2개 이상을 하나의 글자 묶음(.m_txt / .txt)으로 만든다."""
        istxt = lambda s: s[0] == 'leaf' and s[1]['layer'].kind == 'type'
        if all(istxt(s) for s in subs): return subs
        out, run = [], []
        for s in subs + [None]:
            if s is not None and istxt(s): run.append(s); continue
            if len(run) >= 2: out.append(('col', run))
            else: out.extend(run)
            run = []
            if s is not None: out.append(s)
        return out

    def render_seq(self, kind, subs, path, role=None):
        if kind == 'col': subs = self.group_text_runs(subs)
        if len(subs) == 1: return self.render(subs[0], path, role)
        txt_only = all(s[0] == 'leaf' and s[1]['layer'].kind == 'type' for s in subs)
        sizes = {round(self.text_info(s[1]['layer'])[1][0]['font_size_px']) for s in subs if txt_only and self.text_info(s[1]['layer'])[1]}
        is_nav = kind == 'row' and len(subs) >= 3 and txt_only and len(sizes) == 1
        is_tcol = kind == 'col' and txt_only and len(subs) >= 2
        grp = all(s[0] == 'leaf' and s[1]['layer'].is_group() for s in subs)
        ws = [s[1]['bbox'][2] - s[1]['bbox'][0] for s in subs if s[0] == 'leaf']; hs = [s[1]['bbox'][3] - s[1]['bbox'][1] for s in subs if s[0] == 'leaf']
        similar = grp and len(subs) >= 3 and max(ws) - min(ws) <= 0.1 * max(ws) + 2 and max(hs) - min(hs) <= 0.1 * max(hs) + 2
        is_list = len(subs) >= 3 and ((kind == 'row' and all(self.is_card(s) for s in subs)) or similar)
        special = is_nav or is_tcol or is_list
        opath = path; outer = None
        if role and special: outer = self.name(role, path); opath = path + ['.' + outer]
        if is_nav: base = 'gnb' if path and path[0] == ('#' + HID) else 'nav'
        elif is_tcol: base = TTOP if self.card_depth == 0 else TCARD
        elif is_list: base = 'list'
        else: base = role or kind
        cls = self.name(base, opath); p = opath + ['.' + cls]
        croles = [None] * len(subs)
        if kind == 'row' and not special and len(p) <= 3:
            croles = [LC, RC] if len(subs) == 2 else ([LC, CC, RC] if len(subs) == 3 else croles)
        parts, frs = [], []
        for i, s in enumerate(subs):
            k = len(parts)
            cp = p + [f'li:nth-child({k + 1})'] if is_list else p
            q = self.render(s, cp, croles[i], li=is_nav, bare=(is_nav or is_tcol))
            if q.html: parts.append(q)
        if not parts: return Part('', (0, 0, 0, 0), '')
        # 구분선(가로선)을 별도 div 대신 이웃 요소의 border 로: 선 뒤 요소의 border-top, 마지막 선이면 앞 요소의 border-bottom
        borders = {}; line_w = None
        if 'line' in _OPT and kind == 'col' and not special and len(parts) >= 2:
            W_ = max(q.bbox[2] for q in parts) - min(q.bbox[0] for q in parts)
            out_parts = list(parts)
            ok = lambda t: t is not None and t.kind == 'box' and not (t.rec and t.rec.get('hline'))
            for L in [q for q in parts if q.kind == 'shape' and q.rec and q.rec.get('hline')]:
                if (L.bbox[2] - L.bbox[0]) < 0.9 * W_: continue
                pos = out_parts.index(L)
                nxt = out_parts[pos + 1] if pos + 1 < len(out_parts) else None
                prv = out_parts[pos - 1] if pos > 0 else None
                th, col = px(L.rec['thick']), L.rec['color']
                if ok(nxt):
                    pad = nxt.bbox[1] - L.bbox[3]
                    borders.setdefault(id(nxt), []).extend([f'border-top:{th} solid {col}', 'align-self:stretch'] + ([f'padding-top:{px(pad)}'] if pad > 0.5 * self.S else []))
                    nxt.bbox = (nxt.bbox[0], L.bbox[1], nxt.bbox[2], nxt.bbox[3])
                elif ok(prv):
                    pad = L.bbox[1] - prv.bbox[3]
                    borders.setdefault(id(prv), []).extend([f'border-bottom:{th} solid {col}', 'align-self:stretch'] + ([f'padding-bottom:{px(pad)}'] if pad > 0.5 * self.S else []))
                    prv.bbox = (prv.bbox[0], prv.bbox[1], prv.bbox[2], L.bbox[3])
                else:
                    continue
                out_parts.remove(L)
                self.rules.pop(tuple(p + [L.sel]), None)   # 없어진 div.line 의 CSS 도 지운다
            if len(out_parts) != len(parts):
                others_w = max(q.bbox[2] - q.bbox[0] for q in out_parts)
                if W_ - others_w > 2 * self.S: line_w = W_   # 선이 가장 넓으면 묶음 폭을 선 폭으로
                parts = out_parts
        self.set_sels(parts)
        for i, q in enumerate(parts): frs.append(f'li:nth-child({i + 1})' if is_list else q.sel)
        bb = (min(q.bbox[0] for q in parts), min(q.bbox[1] for q in parts), max(q.bbox[2] for q in parts), max(q.bbox[3] for q in parts))
        for q, fr in zip(parts, frs):
            if id(q) in borders: self.rule(p + [fr], borders[id(q)])
        d = ['display:flex']
        if kind == 'row':
            gaps = [round(parts[i + 1].bbox[0] - parts[i].bbox[2]) for i in range(len(parts) - 1)]
            cw = self.cur_cw
            full = cw > 0 and (bb[2] - bb[0]) >= cw - 0.04 * cw   # 섹션 컨테이너 폭을 (거의 정확히) 다 쓰는 행 → 양 끝에 붙은 요소는 auto로
            big = max(gaps) if gaps else 0
            need_w = False
            cf = (len(parts) == 2 and cw > 0 and gaps[0] > 0 and abs((parts[0].bbox[0] + parts[0].bbox[2]) / 2 - self.W / 2) <= 6 * self.S
                  and parts[1].bbox[2] - parts[0].bbox[2] >= 0.05 * cw and parts[0].bbox[0] - (self.W - cw) / 2 >= 0.15 * cw)
            if cf:   # 첫 요소(메뉴 등)가 화면 가운데, 둘째가 오른쪽 끝: 3칸 그리드(가운데 정렬 + 오른쪽 정렬)
                d = ['display:grid', 'grid-template-columns:1fr auto 1fr', 'width:100%']
                self.rule(p + [frs[0]], 'grid-column:2')
                self.rule(p + [frs[1]], ['grid-column:3', 'justify-self:end'])
            elif len(parts) == 2 and gaps[0] >= 0.2 * cw if full else len(parts) == 2 and gaps[0] >= 0.25 * cw:
                d.append('justify-content:space-between'); need_w = True   # 양 끝 정렬: 고정 px 간격 대신
            elif gaps and max(gaps) - min(gaps) <= 2 * self.S and gaps[0] > 0 and not (gaps[0] >= 0.25 * cw):
                d.append('gap:' + px(statistics.median(gaps)))   # 큰 간격(양끝 정렬)은 gap 대신 위의 space-between 이 처리
            else:
                for fr, g in zip(frs[1:], gaps):
                    if g <= 0: continue
                    if full and g == big and g >= 0.2 * cw: self.rule(p + [fr], 'margin-left:auto'); need_w = True   # 오른쪽 끝으로 밀기
                    else: self.rule(p + [fr], 'margin-left:' + px(g))
            if need_w: d.append('width:100%' if full else f'width:{px(bb[2] - bb[0])}; max-width:100%')   # 컨테이너를 꽉 채우면 100%, 아니면 행의 실제 폭(옆 요소가 더 넓어도 늘어나지 않게)   # auto 여백이 남는 공간을 밀어 주려면 행이 컨테이너 폭을 차지해야 한다
            c = [(q.bbox[1] + q.bbox[3]) / 2 for q in parts]; t = [q.bbox[1] for q in parts]; b = [q.bbox[3] for q in parts]
            if max(c) - min(c) <= 3 * self.S: d.append('align-items:center')
            elif max(t) - min(t) <= 2 * self.S: d.append('align-items:flex-start')
            elif max(b) - min(b) <= 2 * self.S: d.append('align-items:flex-end')
            else:
                d.append('align-items:flex-start')
                for fr, q in zip(frs, parts):
                    if q.bbox[1] - min(t) > 0: self.rule(p + [fr], 'margin-top:' + px(q.bbox[1] - min(t)))
        else:
            d.append('flex-direction:column')
            if line_w: d += ['width:' + px(line_w), 'max-width:100%']
            for fr, q, q0 in zip(frs[1:], parts[1:], parts):
                g = q.bbox[1] - q0.bbox[3]
                if g > 0.5 * self.S: self.rule(p + [fr], 'margin-top:' + px(g))
            lf = [q.bbox[0] for q in parts]; ct = [(q.bbox[0] + q.bbox[2]) / 2 for q in parts]; rt = [q.bbox[2] for q in parts]
            if max(lf) - min(lf) <= 2 * self.S: d.append('align-items:flex-start')
            elif max(ct) - min(ct) <= 3 * self.S: d.append('align-items:center')
            elif max(rt) - min(rt) <= 2 * self.S: d.append('align-items:flex-end')
            else:
                d.append('align-items:flex-start')
                auto_used = False
                for fr, q in zip(frs, parts):
                    if q.bbox[0] - min(lf) <= 0: continue
                    if abs(q.bbox[2] - bb[2]) <= 2 * self.S:      # 오른쪽 끝에 맞춘 요소: 고정 margin-left 대신 auto (반응형)
                        self.rule(p + [fr], 'margin-left:auto'); auto_used = True
                    elif abs((q.bbox[0] + q.bbox[2]) / 2 - (bb[0] + bb[2]) / 2) <= 3 * self.S:
                        self.rule(p + [fr], ['margin-left:auto', 'margin-right:auto']); auto_used = True
                    else: self.rule(p + [fr], 'margin-left:' + px(q.bbox[0] - min(lf)))
                if auto_used:  # auto가 의미를 가지려면 묶음의 폭이 정해져 있어야 한다: PSD 폭까지만, 좁아지면 줄어듦
                    d += ['width:100%', 'max-width:' + px(bb[2] - bb[0])]
        self.reg(p, bb)
        self.rule(p, d)
        inner = ''.join((f'<li>{q.html}</li>' if is_list else q.html) for q in parts)
        tagname = 'ul' if (is_nav or is_list) else 'div'
        attr = f'{base} {cls}' if (is_tcol and cls != base) else cls   # 글자 묶음: 공통 클래스(m_txt/txt) 유지
        core = f'<{tagname} class="{attr}">{inner}</{tagname}>'
        if outer: return Part(f'<div class="{outer}">{core}</div>', bb, '.' + outer)
        return Part(core, bb, '.' + cls)

    def render_group(self, g, path, role=None):
        if id(g) in self.chains:  # 그룹 전체에 색 입히기 등 클리핑이 걸린 경우(로고 등): 한 장의 이미지로 저장
            par = g.parent; keep = {id(par), id(g)} | {id(c) for c in self.chains[id(g)]} | {id(d) for d in g.descendants()}
            try: im = par.composite(viewport=g.bbox, force=True, layer_filter=lambda x: id(x) in keep)
            except Exception: im = None
            if im is not None:
                src = self.save_img(im, 'img', self.rid(g)); cls = self.name('img', path); x0, y0, x1, y1 = g.bbox
                self.rule(path + ['.' + cls], ['flex-shrink:0'])
                self.rule(path + ['.' + cls, '.pic'], ['display:block', 'width:' + px(x1 - x0), 'height:auto', 'max-width:100%'])
                self.notes.append(f'{self.sec} .{cls}: 클리핑 효과가 걸린 그룹 "{g.name}"을 이미지 한 장으로 저장(글자 포함).')
                return Part(f'<div class="{cls}"><img class="pic" src="{src}" alt=""></div>', tuple(g.bbox), '.' + cls, 'img')
        kids = [c for c in g if self.vis(c) and id(c) not in self.lifted]
        gx0, gy0, gx1, gy1 = g.bbox; ga = max(1, (gx1 - gx0) * (gy1 - gy0))
        bg = next((c for c in kids if c.kind == 'shape' and all(abs(a - b) <= 3 * self.S for a, b in zip(c.bbox, g.bbox))), None)
        # 작은 버튼: 도형 배경 + 글자 하나
        texts_ = [c for c in kids if c.kind == 'type']
        if bg is not None and len(texts_) == 1 and len(kids) == 2 and (gx1 - gx0) <= 320 * self.S and (gy1 - gy0) <= 80 * self.S and id(bg) not in self.chains:
            return self.render_button(g, bg, texts_[0], path)
        art = [c for c in kids if c is not bg and c.kind in ('pixel', 'smartobject') and c.width * c.height >= 0.3 * ga] if bg else []
        # 클리핑된 사진은 아래 기준(마스크) 도형과 함께 합성해야 보인다
        sibs = list(g); keep_ids = {id(a) for a in art}; art_box = None
        for a in art:
            j = sibs.index(a) - 1
            while j > 0 and sibs[j].clipping: keep_ids.add(id(sibs[j])); j -= 1
            if a.clipping and j >= 0: keep_ids.add(id(sibs[j])); base = sibs[j]
            else: base = None
            b = base.bbox if base is not None else (max(a.bbox[0], gx0), max(a.bbox[1], gy0), min(a.bbox[2], gx1), min(a.bbox[3], gy1))
            art_box = tuple(b) if art_box is None else (min(art_box[0], b[0]), min(art_box[1], b[1]), max(art_box[2], b[2]), max(art_box[3], b[3]))
        rest = [c for c in kids if c is not bg and id(c) not in keep_ids]
        bg_clipped = {id(c) for c in self.chains.get(id(bg), [])} if bg is not None else set()  # 카드 배경 도형에 클리핑된 일러스트 등은 그대로 이미지로 사용
        its = self.merge_blend_cards(self.lift_lines([i for i in (self.item(c, force=id(c) in bg_clipped) for c in rest) if i]))
        tree = self.cut(its) if its else None
        if not bg and not art:  # 단순 묶음 → 구조만 통과
            if not tree: return Part('', tuple(g.bbox), '')
            return self.render(tree, path, role)
        full = bool(art) and all(abs(a - b) <= 3 * self.S for a, b in zip(art_box, g.bbox))
        ox0, oy0, ox1, oy1 = g.bbox
        if bg is not None: gx0, gy0, gx1, gy1 = self.geom(bg)  # 카드의 실제 크기(번짐 여백 제외)
        cls = self.name(role or 'box', path); p = path + ['.' + cls]
        d = ['position:relative', 'box-sizing:border-box', 'flex-shrink:0', 'width:' + px(gx1 - gx0), 'height:' + px(gy1 - gy0)]
        if bg: d += [x for x in self.shape_style(bg) if not (full and x.startswith('background'))]   # 사진이 카드를 꽉 덮으면 검은 도형 배경이 가장자리에 비치지 않게 뺀다
        body = ''
        if art:
            keep = {id(g)} | keep_ids | ({id(bg)} if full else set())
            ax0, ay0, ax1, ay1 = art_box
            cb = (max(ax0, 0), max(ay0, 0), min(ax1, self.W), min(ay1, self.H))  # 캔버스 밖 영역은 합성 시 검게 채워지므로 안쪽만 사용
            im = g.composite(viewport=cb, force=True, layer_filter=lambda x: id(x) in keep) if cb[2] > cb[0] and cb[3] > cb[1] else None
            src = self.save_img(im, 'bg', self.rid(g)) if im is not None else None
            if src:
                ax0, ay0, ax1, ay1 = cb
                pos = [f'left:{px(ax0 - gx0)}', f'top:{px(ay0 - gy0)}', f'width:{px(ax1 - ax0)}', f'height:{px(ay1 - ay0)}']  # 번짐 여백 1px은 overflow로 잘림
                self.rule(p + ['.bg'], ['position:absolute', 'z-index:0'] + pos)
                self.rule(p + ['.bg', '.pic'], ['display:block', 'width:100%', 'height:100%', 'object-fit:cover'])
                body += f'<div class="bg"><img class="pic" src="{src}" alt=""></div>'
                d.append('overflow:hidden')
        inner = ''
        if tree:
            small = (gx1 - gx0) < 600 * self.S; self.card_depth += small
            q = self.render(tree, p)
            self.card_depth -= small
            if q.html:
                if q.kind in ('text', 'btn'):
                    q.sel = f'{q.tag}:nth-child({2 if body else 1})'
                    if q.rec is not None: q.rec['sel'] = q.sel
                d += [f'padding:{px(max(0, q.bbox[1] - gy0))} 0 0 {px(max(0, q.bbox[0] - gx0))}']
                self.rule(p + [q.sel], ['position:relative', 'z-index:1'])
                inner = q.html
        self.reg(p, (gx0, gy0, gx1, gy1))
        self.rule(p, d)
        return Part(f'<div class="{cls}">{body}{inner}</div>', (gx0, gy0, gx1, gy1), '.' + cls, 'card')

    # ---------- 섹션 ----------
    def hairline(self, g):
        """전체 폭의 얇은 선(헤더 하단선 등)을 찾아 border로 바꾼다."""
        for c in g.descendants():
            if self.vis(c) and c.kind == 'shape' and c.width >= 0.9 * self.W and c.height <= 4 * self.S:
                _, gy0, _, gy1 = self.geom(c)  # 실제 선 두께 1px
                try:
                    cl = c.tagged_blocks.get_data(Tag.SOLID_COLOR_SHEET_SETTING)[b'Clr ']
                    col = (cl[b'Rd  '], cl[b'Grn '], cl[b'Bl  '])
                except Exception: col = (0, 0, 0)
                return c, 'rgba(%d,%d,%d,%g)' % (*[round(v) for v in col], round(c.opacity / 255, 2)), gy1
        return None, None, None

    def content_items(self, g, skip):
        out = []
        for c in g:
            if not self.vis(c) or id(c) in skip: continue
            if c.is_group() and any(id(d) in skip for d in c.descendants()):
                kids = [k for k in c.descendants() if self.vis(k) and id(k) not in skip and not k.is_group()]
                if not kids: continue
            out.append(c)
        return out

    def content_top(self, g):
        """섹션 순서 기준: 영역 대부분을 덮는 큰 배경 레이어(전체 캔버스 배경 등)는 빼고 실제 내용이 시작하는 위치."""
        ga = max(1, (g.bbox[2] - g.bbox[0]) * (g.bbox[3] - g.bbox[1]))
        tops = [d.bbox[1] for d in g.descendants() if not d.is_group() and self.vis(d) and d.width * d.height < 0.5 * ga]
        return min(tops) if tops else g.bbox[1]

    def section_bg(self, g):
        """섹션 전체 폭을 덮는 배경 레이어(도형/그림만 있는 것)를 섹션 background로 변환."""
        decl, skip, box = [], set(), None
        for c in g:
            if not self.vis(c) or c.bbox[0] > 2 * self.S or c.bbox[2] < self.W - 2 * self.S: continue
            if getattr(c, 'clipping', False):   # 클리핑 레이어는 바로 아래 배경 그림에 합성되므로 따로 배경으로 쓰지 않는다
                skip.add(id(c)); continue
            leaves = [d for d in c.descendants() if not d.is_group() and self.vis(d)] if c.is_group() else [c]
            if not leaves or any(d.kind not in ('pixel', 'shape') for d in leaves): continue
            skip.add(id(c)); box = tuple(c.bbox) if box is None else (min(box[0], c.bbox[0]), min(box[1], c.bbox[1]), max(box[2], c.bbox[2]), max(box[3], c.bbox[3]))
            if all(d.kind == 'shape' for d in leaves):
                decl += [x for x in self.shape_style(leaves[0]) if x.startswith('background')]
            else:
                im = c.composite(force=True, layer_filter=lambda x: x.is_visible())
                if im is None: continue
                cols = im.convert('RGB').resize((64, 64)).getcolors(4)
                if cols and len(cols) == 1: decl.append('background:' + hexc(cols[0][1]))
                else:
                    src = self.save_img(im, 'bg', self.rid(c))
                    decl += [f'background:url({src}) center top / cover no-repeat']
        if not decl:   # 하위 그룹 안에 들어 있는 전체 폭 단색 배경(예: TXT/BG) → 섹션 배경색으로
            for c in g:
                if not c.is_group() or not self.vis(c): continue
                ca = max(1, (c.bbox[2] - c.bbox[0]) * (c.bbox[3] - c.bbox[1]))
                for d in c.descendants():
                    if d.is_group() or not self.vis(d) or d.kind not in ('pixel', 'shape') or getattr(d, 'clipping', False): continue
                    if d.bbox[0] > 2 * self.S or d.bbox[2] < self.W - 2 * self.S or d.width * d.height < 0.6 * ca: continue
                    im = d.composite(force=True, layer_filter=lambda x: x.is_visible())
                    if im is None: continue
                    cols = im.convert('RGB').resize((64, 64)).getcolors(64)
                    dom = max(cols)[1] if cols else None
                    if cols and all(max(abs(a - b) for a, b in zip(c[1], dom)) <= 6 for c in cols) and (im.mode != 'RGBA' or sum(im.getchannel('A').resize((64, 64)).getdata()) / 4096 >= 240):
                        self.lifted.add(id(d)); box = tuple(d.bbox); decl.append('background:' + hexc(dom)); break
                if decl: break
        lb = self.loose_bg.get(id(g))
        if not decl and lb is not None:   # 그룹 밖(루트)의 전체 폭 단색 배경
            try:
                im = lb.composite(force=True, layer_filter=lambda x: x.is_visible())
                cols = im.convert('RGB').resize((64, 64)).getcolors(64)
                dom = max(cols)[1] if cols else None
                if cols and all(max(abs(a - b) for a, b in zip(c[1], dom)) <= 6 for c in cols):
                    decl.append('background:' + hexc(dom)); box = tuple(lb.bbox)
            except Exception:
                pass
        return decl, skip, box

    def auto_widths(self, groups, header, fixed):
        """컨테이너 폭 자동 인식: 각 섹션 내용의 가로 폭을 모아 가장 많은 폭을 inner, 그보다 넓은 쪽에서 가장 많은 폭을 wide 로 쓴다."""
        global INNER, WIDE
        if not (AUTO['inner'] or AUTO['wide']): return
        ws = []
        for g in groups:
            if g is header or fixed(g): continue
            xs = [(c.bbox[0], c.bbox[2]) for c in g if self.vis(c) and 0 < c.width < 0.9 * self.W]
            if xs: ws.append((max(b for _, b in xs) - min(a for a, _ in xs)) / self.S)
        ws = sorted(w for w in ws if w >= 600)
        buckets = []
        for w in ws:
            if buckets and w - buckets[-1][0] <= 30: buckets[-1].append(w)
            else: buckets.append([w])
        top = lambda bs: max(bs, key=lambda b: (len(b), max(b))) if bs else None
        pick = lambda b: int(math.ceil(max(b) / 10.0) * 10)
        msg = []
        if len(ws) < 2:
            self.notes.append('컨테이너 폭 자동 인식: 섹션이 부족해 기본값을 씁니다'); return
        inner = pick(top(buckets))
        if AUTO['inner']: INNER = inner; msg.append(f'inner {INNER}px')
        if AUTO['wide']:
            wide_b = [b for b in buckets if min(b) > INNER + 30]
            WIDE = pick(top(wide_b)) if wide_b else max(DEFAULT_CONV['wide'], INNER + 200)
            msg.append(f'wide {WIDE}px')
        if INNER >= WIDE: WIDE = INNER + 200
        self.notes.append(f'컨테이너 폭 자동 인식: {" / ".join(msg)} (섹션 {len(ws)}개 분석)')

    def build(self, out):
        self.out = out
        groups = [l for l in self.psd if l.is_group() and self.vis(l)]
        if self.only: groups = [g for g in groups if any(o.lower() in g.name.lower() for o in self.only)]
        groups.sort(key=self.content_top)
        for l in self.psd:   # 그룹 밖 전체 폭 배경 레이어 → 그 범위 안에 든 섹션의 배경
            if l.is_group() or not self.vis(l) or l.kind not in ('pixel', 'shape') or l.bbox[0] > 2 * self.S or l.bbox[2] < self.W - 2 * self.S or l.height >= 0.9 * self.H: continue
            for g in groups:
                if l.bbox[1] - 2 * self.S <= g.bbox[1] and g.bbox[3] <= l.bbox[3] + 2 * self.S and id(g) not in self.loose_bg and not self.hidden & {id(l)}: self.loose_bg[id(g)] = l
        header = next((g for g in groups if re.search(r'top|header|헤더', g.name, re.I) and g.height < 200 * self.S), None)
        fixed = lambda g: g.bbox[0] > 0.9 * self.W and g.height < 0.5 * self.H
        self.auto_widths(groups, header, fixed)
        top = bottom = aside = ''; hdr_bottom = 0; n = 0
        total = max(1, len(groups)); done = 0
        self.emit(40, f'화면 구조를 분석하는 중 (영역 {len(groups)}개)')
        if header:
            self.emit(42, '헤더를 변환하는 중')
            self.sec = 'header'
            line, col, ly = self.hairline(header)
            skip = {id(line)} | {id(x) for x in line.parent.descendants()} if line is not None and line.parent is not self.psd and len(list(line.parent)) == 1 else ({id(line)} if line is not None else set())
            self.hidden |= skip
            hb = ly if ly else header.bbox[3]
            hdr_loose = [c for c in self.psd if not c.is_group() and self.vis(c) and c.bbox[3] <= hb + 2 * self.S and c.height < hb and c.width < 0.5 * self.W]   # 그룹 밖에 있는 로고 등
            its = self.merge_blend_cards(self.lift_lines([i for i in (self.item(c) for c in self.content_items(header, skip) + hdr_loose) if i]))
            self.cur_cw = WIDE * self.S
            q = self.render(self.cut(its), [('#' + HID), ('.' + WCLS)]) if its else Part('', (0, 0, 0, 0), '')
            hh = round(ly) if ly else round(header.bbox[3])
            self.rules[(('#' + HID),)] = ['position:relative', 'width:100%', 'background:#fff', f'height:{px(hh)}'] + ([f'border-bottom:1px solid {col}', 'box-sizing:border-box'] if line is not None else [])
            self.rules[(('#' + HID), ('.' + WCLS))] = ['height:100%', 'display:flex', 'align-items:center']
            if q.html:   # 헤더 내용이 넓은 컨테이너(1600)보다 넓게 펼쳐진 디자인: 헤더는 전체 폭 + 좌우 같은 여백
                hx0, hx1 = q.bbox[0], q.bbox[2]; cb = (self.W - WIDE * self.S) / 2
                if hx1 > self.W - cb + 2 * self.S or hx0 < cb - 2 * self.S:
                    l_pad, r_pad = max(0, hx0), max(0, self.W - hx1)
                    pad = f'padding:0 {px(l_pad)}' if abs(l_pad - r_pad) <= 3 * self.S else f'padding:0 {px(r_pad)} 0 {px(l_pad)}'   # 좌우 여백이 다르면 각각 지정
                    self.rules[(('#' + HID), ('.' + WCLS))] += ['width:100%', pad, 'box-sizing:border-box']
            hdr_bottom = hh
            self.sec_ranges[HID] = (0, hh, 'header')
            top = f'<header id="{HID}"><div class="{WCLS}">{q.html}</div></header>'
        prev = hdr_bottom; bodies = []; first = True
        for g in groups:
            if g is header: continue
            done += 1
            self.emit(44 + 36 * done / total, f'변환 중: {re.sub(r"[^0-9A-Za-z가-힣 ._-]", "", g.name)[:30]} ({done}/{total})')
            if fixed(g):  # 오른쪽 고정 퀵메뉴
                self.sec = 'quick'
                it = self.item(g)
                if not it: continue
                q = self.render(('leaf', it), [('#' + QID)])
                x0, y0, x1, y1 = g.bbox
                self.rules[(('#' + QID),)] = ['position:fixed', f'right:{px(self.W - x1)}', f'top:{px(y0)}', 'z-index:999']
                aside = f'<aside id="quick">{q.html}</aside>'
                self.notes.append(f'#quick ← PSD 그룹 "{g.name}" ({self.rid(g)}): 화면 오른쪽에 고정(position:fixed)')
                continue
            is_footer = bool(re.search(r'foot|푸터', g.name, re.I))
            if is_footer: sid = FID
            elif first: sid = VID
            else: n += 1; sid = f'{SPFX}{n}'
            first = first and is_footer
            self.sec = sid
            self.sec_names[sid] = re.sub(r'[^0-9A-Za-z가-힣 ._-]', '', g.name)
            self.sec_ranges[sid] = (g.bbox[1], g.bbox[3], self.sec_names[sid])
            bg_decl, bg_skip, bg_box = self.section_bg(g)
            its = self.merge_blend_cards(self.lift_lines([i for i in (self.item(c) for c in g if self.vis(c) and id(c) not in bg_skip) if i]))
            if not its: continue
            w = max(i['bbox'][2] for i in its) - min(i['bbox'][0] for i in its)
            wide = w > (INNER + 10) * self.S; box = WCLS if wide else BCLS
            self.cur_cw = (WIDE if wide else INNER) * self.S
            q = self.render(self.cut(its), ['#' + sid, '.' + box])
            x0, y0, x1, y1 = q.bbox
            base = (self.W - (WIDE if wide else INNER) * self.S) / 2
            top0, bot0 = (bg_box[1], bg_box[3]) if bg_box else (prev, y1)
            if top0 > y0: top0 = y0
            if bot0 < y1: bot0 = y1
            self.rules[('#' + sid,)] = [f'margin-top:{px(max(0, top0 - prev))}', f'padding-top:{px(max(0, y0 - max(top0, prev)))}', f'padding-bottom:{px(max(0, bot0 - y1))}', 'overflow:hidden'] + bg_decl
            cw = (WIDE if wide else INNER) * self.S
            left_over, right_over = x0 - base < -2 * self.S, x1 > base + cw + 2 * self.S
            if (left_over or right_over) and abs((x0 + x1) / 2 - self.W / 2) <= 4 * self.S and q.kind not in ('text', 'btn'):
                # 컨테이너보다 넓지만 좌우 대칭(슬라이드 등): 가운데 정렬로 양쪽 균등하게 넘치게 한다
                self.rules.setdefault(('#' + sid, '.' + box), []).extend(['display:flex', 'justify-content:center'])
                self.rules.setdefault(('#' + sid, '.' + box, q.sel), []).append('flex-shrink:0')  # 기존 규칙(display:flex …)에 합친다
            elif x0 - base > 2 * self.S and abs((x0 - base) - (base + cw - x1)) <= 4 * self.S:   # 좌우 여백이 같으면 양쪽 패딩(폭을 넘치지 않게)
                self.rules[('#' + sid, '.' + box)] = [f'padding:0 {px(x0 - base)}', 'box-sizing:border-box']
            elif x0 - base > 2 * self.S: self.rules[('#' + sid, '.' + box)] = [f'padding-left:{px(x0 - base)}']
            elif left_over: self.rules[('#' + sid, '.' + box)] = ['position:relative', f'left:{px(x0 - base)}']  # 왼쪽으로 삐져나간 행(로고 슬라이드 등)
            prev = bot0
            if is_footer: bottom = f'<footer id="footer"><div class="{box}">{q.html}</div></footer>'
            else: bodies.append(f'<section id="{sid}"><div class="{box}">{q.html}</div></section>')
            self.notes.append(f'#{sid} ← PSD 그룹 "{g.name}" ({self.rid(g)})')
        self.emit(82, '공통 스타일을 묶고 CSS를 만드는 중')
        return self.finish(top, '<main id="' + CID + '">' + ''.join(bodies) + '</main>', bottom, aside)

    # ---------- 공통 스타일 묶기 + CSS 출력 ----------
    SEMP = re.compile(r'^\.(m_txt|txt|gnb|nav)\d*$')   # set_conv 후 __init__ 에서 다시 만든다

    @staticmethod
    def diff(sig, base):
        """공통(base)과 다른 선언만. base에는 있는데 sig에는 없는 속성은 initial로 되돌린다."""
        if not base: return list(sig)
        keys = {x.split(':')[0] for x in sig}
        return [x for x in sig if x not in base] + [x.split(':')[0] + ':initial' for x in base if x.split(':')[0] not in keys]

    def finish(self, top, main, footer, aside):
        """공통 스타일은 한 번만 정의(전역), 공통이 없으면 섹션 부모를 둔 선택자(#sec1 .l_cont .txt h3)로 정의."""
        glob = OrderedDict()  # 선택자 튜플 → 선언
        # 1) 글자: (.m_txt|.txt|.gnb|.nav, 태그) 별로 2번 이상 쓰인 스타일이 있으면 그것을 전역 기본으로
        groups = {}
        for r in self.texts:
            if not r['decls']: continue
            par = r['path'][-1] if r['path'] else ''
            m = self.SEMP.match(par)
            if m: groups.setdefault(('.' + m.group(1), r['tag']), []).append(r)
            elif r['sel']: self.rule(r['path'] + [r['sel']], r['decls'])
        for (par, tag), rs in groups.items():
            cnt = Counter(tuple(r['decls']) for r in rs)
            commons = [s for s, c in cnt.most_common() if c >= 2]
            base = commons[0] if commons else None
            if base: glob[(par, tag)] = list(base)
            for r in rs:
                sig = tuple(r['decls'])
                if base and sig == base: continue
                decls = self.diff(sig, base)
                if r['sel'] and decls: self.rule(r['path'] + [r['sel']], decls)
        for r in self.texts:  # 문단 정렬 등은 그 글자에만
            if r.get('extra') and r['sel']: self.rule(r['path'] + [r['sel']], r['extra'])
        # 2) 공백으로 띄운 구간: span 앞 간격을 margin-left로
        for r in self.texts:
            for k, g in r['gaps']:
                if r['sel']: self.rule(r['path'] + [r['sel'], f'span:nth-of-type({k})'], f'margin-left:{px(g)}')
        # 3) 버튼/배지: 클래스별 공통 스타일은 전역(.more), 다른 것은 섹션 스코프로 차이만
        bgrp = {}
        for r in self.btns: bgrp.setdefault(r['cls'], []).append(r)
        for cls, rs in bgrp.items():
            cnt = Counter(tuple(r['decls']) for r in rs)
            commons = [s for s, c in cnt.most_common() if c >= 2]
            base = commons[0] if commons else None
            if base: glob[('.' + cls,)] = list(base)
            for r in rs:
                sig = tuple(r['decls'])
                if base and sig == base: continue
                decls = self.diff(sig, base)
                if r['sel'] and decls: self.rule(r['path'] + [r['sel']], decls)
                elif decls: self.notes.append(f'{" ".join(r["path"])}: 버튼 스타일 위치를 지정하지 못했습니다.')

        # 3-1) 길이 숫자 반올림: 소수점 제거, 10px 이상은 5px 단위, 10px 미만은 2px 단위(5 포함)로 가장 가까운 값
        #      (글자 크기·테두리 두께·둥근 모서리는 그대로 둔다)
        SPACING = re.compile(r'^(?:margin|padding)(?:-(?:top|right|bottom|left))?$|^(?:gap|row-gap|column-gap)$')
        SNAP_PROP = re.compile(r'^(?:margin|padding)(?:-(?:top|right|bottom|left))?$|^(?:gap|row-gap|column-gap|width|height|min-width|max-width|min-height|max-height|left|right|top|bottom)$')

        def snap(v):
            sg = -1 if v < 0 else 1
            a = abs(v)
            if a < 2: r = round(a)
            elif a < 10: r = min([2, 4, 5, 6, 8, 10], key=lambda c: (abs(c - a), -c))   # 같은 거리면 큰 값
            else: r = int(a / 5 + 0.5) * 5
            return sg * r

        def snap_decl(x):
            k, v = x.split(':', 1)
            kk = k.strip()
            if not SNAP_PROP.match(kk): return x
            # tidy: 간격(margin·padding·gap)은 5px·2px 단위, 크기·위치는 정수 / exact: 모두 정수로만
            use_unit = self.css_round != 'exact' and SPACING.match(kk)
            f = (lambda t: snap(t)) if use_unit else (lambda t: round(t))
            return k + ':' + re.sub(r'(-?\d+(?:\.\d+)?)px', lambda m: f'{f(float(m.group(1))):g}px', v)
        def tidy_decl(x):
            """남은 소수점 정리: px 는 정수, line-height(em)는 소수 1자리, 그 밖의 em·투명도·rgba 알파는 소수 2자리(뒤의 0 제거)"""
            k, v = x.split(':', 1)
            kk = k.strip()
            v = re.sub(r'(-?\d+\.\d+)em', lambda m: f'{round(float(m.group(1)), 1 if kk == "line-height" else 2):g}em', v)
            v = re.sub(r'(-?\d+\.\d+)px', lambda m: f'{round(float(m.group(1))):g}px', v)
            if kk == 'opacity':
                try: v = f'{round(float(v), 2):g}'
                except ValueError: pass
            v = re.sub(r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)', lambda m: f'rgba({m.group(1)},{m.group(2)},{m.group(3)},{round(float(m.group(4)), 2):g})', v)
            return k + ':' + v
        if 'snap' in _OPT:
            for path_ in list(self.rules): self.rules[path_] = [tidy_decl(snap_decl(x)) for x in self.rules[path_]]
            for path_ in list(glob): glob[path_] = [tidy_decl(snap_decl(x)) for x in glob[path_]]

        # 4) 선택자 최적화: 자손(공백) 선택자와 자식(>) 선택자가 DOM에서 똑같은 요소를 가리킬 때만 공백 형태 사용
        self.emit(85, 'CSS 선택자를 실제 HTML과 대조해 검증하는 중')
        dom = _Dom(top + main + footer + aside)

        # 3-2) 반복되는 같은 요소(li:nth-child(1)~(N))의 똑같은 CSS 는 한 번만: li:nth-child(k) → li
        #      합친 선택자가 원래 요소들과 정확히 같은 요소를 가리킬 때만 합친다(DOM 으로 검증)
        LI = re.compile(r'li:nth-child\(\d+\)')
        groups_ = {}
        for path_, decls_ in list(self.rules.items()):
            if any(LI.fullmatch(t) for t in path_):
                norm = tuple('li' if LI.fullmatch(t) else t for t in path_)
                groups_.setdefault((norm, tuple(decls_)), []).append(path_)
        merged_n = 0
        for (norm, dec), paths_ in groups_.items():
            if 'merge' not in _OPT or len(paths_) < 2: continue
            union = frozenset().union(*[dom.select(pp, '>') for pp in paths_])
            if union and dom.select(norm, '>') == union:
                for pp in paths_: del self.rules[pp]
                self.rules.setdefault(norm, []).extend(dec)
                merged_n += len(paths_) - 1
        if merged_n: self.notes.append(f'반복되는 같은 요소의 중복 CSS {merged_n}줄을 합쳤습니다.')

        def sel_str(path):
            kids = dom.select(path, '>')
            if not kids:
                self.notes.append(f'스타일이 적용될 요소가 없는 규칙: {" > ".join(path)}')
                return ' > '.join(path)
            return ' '.join(path) if dom.select(path, ' ') == kids else ' > '.join(path)

        def block(path, decls):
            """한 줄 규칙: 선택자{속성: 값; 속성: 값;}"""
            seen = OrderedDict()
            for x in decls: seen[x.split(':')[0]] = x
            items = []
            for x in seen.values():
                k, v = x.split(':', 1); items.append(f'{k}: {v.strip()}')
            return f'{sel_str(path)}{{{"; ".join(items)};}}'

        def banner(text):
            return f'/* ===== {text} ===== */'

        def grouped(items, titles):
            """섹션(#mVisual, #sec1 …)별로 제목 주석 + 빈 줄로 구분, 같은 섹션 안에서도 부모(.l_cont/.r_cont …)가 바뀌면 한 줄 띄움."""
            by_sec = OrderedDict()
            for p, d in items: by_sec.setdefault(p[0], []).append((p, d))
            chunks = []
            for sid, rs in by_sec.items():
                groups = OrderedDict()
                for p, d in rs: groups.setdefault(tuple(p[:4]), []).append((p, d))
                ordered = sorted(groups.items(), key=lambda kv: min(len(kv[0]), 4))  # 섹션 자체 규칙(짧은 경로)을 맨 위에, 나머지는 등장 순서 유지
                title = titles.get(sid.lstrip('#'), '')
                body = '\n\n'.join('\n'.join(block(p, d) for p, d in sorted(g, key=lambda pd: len(pd[0]))) for _, g in ordered)  # 부모 규칙 → 자식 규칙 순
                chunks.append(banner(sid + (f'  ·  {title}' if title else '')) + '\n' + body)
            return '\n\n\n'.join(chunks)

        def commons(items):
            """공통 스타일: 같은 첫 선택자(.txt, .m_txt, .btn …)끼리 묶고 다른 묶음 사이는 빈 줄."""
            groups = OrderedDict()
            for p, d in items: groups.setdefault(p[0], []).append((p, d))
            return '\n\n'.join('\n'.join(block(p, d) for p, d in g) for g in groups.values())
        # header / footer / quick 은 layout.css, 섹션과 공통 스타일은 main.css (default.css는 기본틀의 reset·폰트 정의를 그대로 사용)
        is_layout = lambda p: p[0] in (('#' + HID), ('#' + FID), ('#' + QID))
        lay_glob = [(p, d) for p, d in glob.items() if any('.gnb' in t for t in p)]
        main_glob = [(p, d) for p, d in glob.items() if not any('.gnb' in t for t in p)]
        lay_rules = [(p, d) for p, d in self.rules.items() if is_layout(p)]
        sec_rules = [(p, d) for p, d in self.rules.items() if not is_layout(p)]
        layout_css = banner('공통: 메뉴') + '\n.gnb a, .nav a{color: inherit;}\n' + commons(lay_glob) + '\n\n\n' + grouped(lay_rules, self.sec_names)
        main_css = banner('공통 스타일 (같은 모양은 한 번만 정의)') + '\n' + commons(main_glob) + '\n\n\n' + grouped(sec_rules, self.sec_names)
        elems = []
        for path, bb, rec in self.elems:
            tail = [rec['sel'] or rec.get('tag') or ''] if rec else []
            sel = ' > '.join([x for x in list(path) + tail if x])
            elems.append((sel, int(bb[0]), int(bb[1]), int(bb[2] - bb[0]), int(bb[3] - bb[1])))
        return {'header': top, 'main': main, 'footer': footer, 'quick': aside, 'layout_css': layout_css, 'main_css': main_css, 'elems': elems, 'fonts': sorted({g for g in self.fonts_used.values() if g})}


# ---------- 선택자 검증용 미니 DOM ----------
from html.parser import HTMLParser

class _Node:
    __slots__ = ('tag', 'id', 'cls', 'parent', 'kids', 'nthc', 'ntht')
    def __init__(self, tag): self.tag, self.id, self.cls, self.parent, self.kids, self.nthc, self.ntht = tag, None, set(), None, [], 0, 0

class _Dom(HTMLParser):
    VOID = {'img', 'br', 'input', 'meta', 'link', 'hr'}
    TOK = re.compile(r'#([\w-]+)|\.([\w-]+)|:nth-child\((\d+)\)|:nth-of-type\((\d+)\)|^([a-zA-Z][\w]*)')

    def __init__(self, src):
        super().__init__(convert_charrefs=True)
        self.root = _Node('#root'); self.cur = self.root; self.all = []; self.cache = {}
        self.feed(src)

    def handle_starttag(self, tag, attrs):
        n = _Node(tag); a = dict(attrs); n.id = a.get('id'); n.cls = set((a.get('class') or '').split())
        n.parent = self.cur; self.cur.kids.append(n)
        n.nthc = len(self.cur.kids); n.ntht = sum(1 for k in self.cur.kids if k.tag == tag)
        self.all.append(n)
        if tag not in self.VOID: self.cur = n

    def handle_endtag(self, tag):
        c = self.cur
        while c is not self.root and c.tag != tag: c = c.parent
        if c is not self.root: self.cur = c.parent

    def comp(self, s):
        if s not in self.cache: self.cache[s] = [m.groups() for m in self.TOK.finditer(s)]
        return self.cache[s]

    def ok(self, n, s):
        for id_, cl, nc, nt, tg in self.comp(s):
            if id_ and n.id != id_: return False
            if cl and cl not in n.cls: return False
            if nc and n.nthc != int(nc): return False
            if nt and n.ntht != int(nt): return False
            if tg and n.tag != tg: return False
        return True

    def chain(self, n, path, i, comb):
        if not self.ok(n, path[i]): return False
        if i == 0: return True
        p = n.parent
        if comb == '>': return p is not None and p is not self.root and self.chain(p, path, i - 1, comb)
        while p is not None and p is not self.root:
            if self.chain(p, path, i - 1, comb): return True
            p = p.parent
        return False

    def select(self, path, comb):
        path = list(path)
        return frozenset(id(n) for n in self.all if self.ok(n, path[-1]) and self.chain(n, path, len(path) - 1, comb))
