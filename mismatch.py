"""PSD 합성본과 변환 결과가 다른 구간을 찾아 보고서(HTML·JSON·Markdown + 구간 이미지)로 남긴다.

- 구간 탐지: 16px 블록 단위로 차이를 모아 이어진 덩어리(큰 순서)를 구간으로 본다.
- 관련 정보: 섹션, 겹치는 PSD 레이어, 겹치는 HTML 요소(CSS 선택자), 몇 px 어긋났는지, 점검 포인트
"""
import html as _html
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

BLOCK = 16
MAX_REGIONS = 24
DIFF_THRESHOLD = 40

SELS = '#header *, #content *, #footer *, #quick *'   # 규칙(pengo-rules.json)에 따라 publisher 가 바꾼다
RECT_SCRIPT = """<script>window.addEventListener('load',function(){setTimeout(function(){
function sel(e){var p=[],n=e;while(n&&n.nodeType==1&&n.tagName!='BODY'&&n.tagName!='HTML'){var s=n.tagName.toLowerCase();if(n.id){p.unshift('#'+n.id);break;}if(n.classList.length)s='.'+n.classList[0];p.unshift(s);n=n.parentElement;}return p.join(' ');}
var out=[];document.querySelectorAll('__SELS__').forEach(function(e){var r=e.getBoundingClientRect();if(r.width<2||r.height<2)return;out.push([sel(e),Math.round(r.left+scrollX),Math.round(r.top+scrollY),Math.round(r.width),Math.round(r.height)]);});
try{var x=new XMLHttpRequest();x.open('POST','http://127.0.0.1:__PORT__/',false);x.setRequestHeader('Content-Type','text/plain');x.send(JSON.stringify(out));}catch(e){}},400);});</script>"""


def dump_rects(browser, out, W, H, profile, flags):
    """생성된 페이지를 브라우저로 열어 요소별 위치(페이지 좌표)를 얻는다. 실패하면 빈 목록.
    페이지가 내 컴퓨터(127.0.0.1)의 임시 서버로만 데이터를 보낸다. 외부로 나가지 않는다."""
    import http.server
    import threading
    box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get('Content-Length', 0))
            box['data'] = self.rfile.read(n).decode('utf-8', 'replace')
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.end_headers()

        def log_message(self, *a):
            pass

    tmp = Path(out) / '.psdpub-measure.html'
    shot = Path(out) / '.psdpub-measure.png'
    srv = None
    try:
        srv = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        src = (Path(out) / 'preview.html').read_text(encoding='utf-8')
        script = RECT_SCRIPT.replace('__PORT__', str(port)).replace('__SELS__', SELS)
        tmp.write_text(src.replace('</body>', script + '</body>') if '</body>' in src else src + script, encoding='utf-8')
        subprocess.run([browser, f'--user-data-dir={profile}', '--headless=new', '--disable-gpu', '--hide-scrollbars', f'--window-size={W},{H + 400}',
                        '--virtual-time-budget=8000', f'--screenshot={shot}', tmp.as_uri()], capture_output=True, timeout=90, creationflags=flags)
        return json.loads(box['data']) if box.get('data') else []
    except Exception:
        return []
    finally:
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        for f in (tmp, shot):
            try:
                f.unlink()
            except Exception:
                pass


def _regions(diff):
    """차이 마스크 → [(x, y, w, h, 차이픽셀수)] (차이 많은 순)"""
    H, W = diff.shape
    Hb, Wb = (H + BLOCK - 1) // BLOCK, (W + BLOCK - 1) // BLOCK
    pad = np.zeros((Hb * BLOCK, Wb * BLOCK), dtype=np.uint16)
    pad[:H, :W] = diff
    counts = pad.reshape(Hb, BLOCK, Wb, BLOCK).sum(axis=(1, 3))
    grid = counts >= 10
    near = grid.copy()  # 한 블록 이내로 가까운 덩어리는 하나로
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near |= np.roll(np.roll(grid, dy, 0), dx, 1)
    seen = np.zeros_like(near)
    out = []
    for sy in range(Hb):
        for sx in range(Wb):
            if not near[sy, sx] or seen[sy, sx]:
                continue
            stack, cells = [(sy, sx)], []
            seen[sy, sx] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < Hb and 0 <= nx < Wb and near[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            x0, y0 = min(xs) * BLOCK, min(ys) * BLOCK
            x1, y1 = min(W, (max(xs) + 1) * BLOCK), min(H, (max(ys) + 1) * BLOCK)
            n = int(diff[y0:y1, x0:x1].sum())
            if n >= 350:
                out.append((x0, y0, x1 - x0, y1 - y0, n))
    out.sort(key=lambda r: -r[4])
    return out[:MAX_REGIONS]


def _best_shift(page_g, ref_g, box, maxs=6):
    """이 구간이 가로·세로로 몇 px 어긋났는지 추정. (dx, dy, 개선된 차이 비율) 또는 None"""
    x, y, w, h = box
    cx, cy = x + w // 2, y + h // 2
    w, h = min(w, 360), min(h, 360)
    x, y = max(0, cx - w // 2), max(0, cy - h // 2)
    H, W = ref_g.shape
    w, h = min(w, W - x), min(h, H - y)
    ref = ref_g[y:y + h, x:x + w].astype(np.int16)
    base = int((np.abs(page_g[y:y + h, x:x + w].astype(np.int16) - ref) > DIFF_THRESHOLD).sum())
    if base == 0:
        return None
    best = (0, 0, base)
    for dy in range(-maxs, maxs + 1):
        for dx in range(-maxs, maxs + 1):
            if dx == 0 and dy == 0:
                continue
            if y + dy < 0 or x + dx < 0 or y + dy + h > page_g.shape[0] or x + dx + w > page_g.shape[1]:
                continue
            c = int((np.abs(page_g[y + dy:y + dy + h, x + dx:x + dx + w].astype(np.int16) - ref) > DIFF_THRESHOLD).sum())
            if c < best[2]:
                best = (dx, dy, c)
    # 어긋남을 보정했을 때 차이가 40% 이상 줄어야 "어긋남"으로 본다
    if best[2] <= base * 0.6:
        return {'dx': best[0], 'dy': best[1], 'diff_before': round(100 * base / (w * h), 1), 'diff_after': round(100 * best[2] / (w * h), 1)}
    return None


def _layers_in(manifest, box):
    x, y, w, h = box
    res = []
    for row in manifest.get('layers', []):
        if not row.get('effective_visible') or row['kind'] == 'group':
            continue
        bx0, by0, bx1, by1 = row['bbox']
        ix0, iy0, ix1, iy1 = max(x, bx0), max(y, by0), min(x + w, bx1), min(y + h, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        ov = (ix1 - ix0) * (iy1 - iy0)
        area = max(1, (bx1 - bx0) * (by1 - by0))
        if area > 6 * max(1, w * h):  # 페이지 전체를 덮는 배경 레이어는 제외
            continue
        if ov / area < 0.25 and ov / max(1, w * h) < 0.25:
            continue
        label = (row.get('text') or row['name']).strip().replace('\n', ' ')[:28]
        res.append((ov, {'id': row['id'], 'kind': row['kind'], 'name': label, 'bbox': [bx0, by0, bx1 - bx0, by1 - by0]}))
    res.sort(key=lambda t: -t[0])
    return [r for _, r in res[:8]]


def _elements_in(rects, box):
    """영역과 겹치는 HTML 요소 중 가장 구체적인(작은) 것들"""
    x, y, w, h = box
    found = []
    for sel, rx, ry, rw, rh in rects:
        ix0, iy0, ix1, iy1 = max(x, rx), max(y, ry), min(x + w, rx + rw), min(y + h, ry + rh)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        ov = (ix1 - ix0) * (iy1 - iy0)
        area = max(1, rw * rh)
        if ov / area < 0.4 and ov / max(1, w * h) < 0.5:
            continue
        if area > 6 * w * h:
            continue
        found.append((area, {'selector': sel, 'rect': [rx, ry, rw, rh]}))
    found.sort(key=lambda t: t[0])
    seen, out = set(), []
    for _, e in found:
        if e['selector'] in seen:
            continue
        seen.add(e['selector'])
        out.append(e)
        if len(out) >= 6:
            break
    return out


def _section_of(sec_ranges, box):
    x, y, w, h = box
    best, bov = None, 0
    for sid, (y0, y1, name) in sec_ranges.items():
        ov = min(y + h, y1) - max(y, y0)
        if ov > bov:
            best, bov = (sid, name), ov
    return best


def _hint(layers, box):
    area = box[2] * box[3]
    kinds = [l['kind'] for l in layers]
    big_img = any(l['kind'] in ('pixel', 'smartobject') and l['bbox'][2] * l['bbox'][3] >= 0.4 * area for l in layers)
    if big_img:
        return '이미지: 위치·크기·잘림, 사진 위 겹침 효과(그라데이션·어둡게)를 확인하세요.'
    if 'type' in kinds:
        return '글자: 글꼴(Pretendard 로딩 여부)·글자 크기·자간·줄 간격·정렬 위치를 확인하세요.'
    if 'shape' in kinds:
        return '도형: 배경색·둥근 모서리·테두리·그림자·위치를 확인하세요.'
    return '배경·여백: 섹션 배경색이나 위/아래 간격(margin·padding)을 확인하세요.'


def build_report(out, ref, page, pct, manifest, sec_ranges, rects):
    """보고서 파일 생성. 반환: 구간 수"""
    out = Path(out)
    W, H = ref.size
    h = min(page.height, H)
    a = np.array(page.crop((0, 0, W, h)).convert('L'), dtype=np.int16)
    b = np.array(ref.crop((0, 0, W, h)).convert('L'), dtype=np.int16)
    diff = (np.abs(a - b) > DIFF_THRESHOLD)
    if h < H:  # 페이지가 짧으면 모자란 부분은 전부 불일치
        diff = np.vstack([diff, np.ones((H - h, W), dtype=bool)])
        a = np.vstack([a, np.zeros((H - h, W), dtype=np.int16)])
        b = np.array(ref.convert('L'), dtype=np.int16)
    regs = _regions(diff.astype(np.uint16))
    folder = out / 'analysis' / 'mismatch'
    folder.mkdir(parents=True, exist_ok=True)
    page_rgb = page.convert('RGB')
    page_rgb = page_rgb.crop((0, 0, W, min(page_rgb.height, H)))
    if page_rgb.height < H:
        canvas = Image.new('RGB', (W, H), (255, 255, 255))
        canvas.paste(page_rgb, (0, 0))
        page_rgb = canvas
    ref_rgb = ref.convert('RGB')
    page_g, ref_g = a.astype(np.uint8), b.astype(np.uint8)
    items = []
    for i, (x, y, w, hh, n) in enumerate(regs, 1):
        pad = 12
        cx0, cy0, cx1, cy1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + hh + pad)
        files = {}
        crops = {'psd': ref_rgb.crop((cx0, cy0, cx1, cy1)), 'page': page_rgb.crop((cx0, cy0, cx1, cy1))}
        d = diff[cy0:cy1, cx0:cx1]
        base = np.array(crops['page'], dtype=np.float32) * 0.35 + 255 * 0.65
        base[d] = (230, 40, 40)
        crops['diff'] = Image.fromarray(base.astype(np.uint8))
        for k, im in crops.items():
            if im.width > 1400:
                im = im.resize((1400, max(1, round(im.height * 1400 / im.width))), Image.LANCZOS)
            name = f'region-{i:02d}-{k}.png'
            im.save(folder / name)
            files[k] = f'mismatch/{name}'
        box = (x, y, w, hh)
        sec = _section_of(sec_ranges, box)
        layers = _layers_in(manifest, box)
        items.append({
            'no': i,
            'region': {'x': x, 'y': y, 'width': w, 'height': hh},
            'diff_percent': round(100 * n / max(1, w * hh), 1),
            'diff_pixels': n,
            'section': {'id': sid_fmt(sec[0]), 'psd_group': sec[1]} if sec else None,
            'hint': _hint(layers, box),
            'shift': _best_shift(page_g, ref_g, box),
            'psd_layers': layers,
            'html_elements': _elements_in(rects, box),
            'images': files,
        })
    report = {'match_percent': round(pct, 2), 'canvas': [W, H], 'region_count': len(items),
              'how_to_read': '구간은 차이가 큰 순서입니다. images의 psd=PSD 합성본, page=변환 결과, diff=빨간 부분이 다른 픽셀입니다.',
              'regions': items}
    (out / 'analysis' / 'mismatch-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'analysis' / 'mismatch-report.md').write_text(_markdown(report), encoding='utf-8')
    (out / 'analysis' / 'mismatch-report.html').write_text(_html_doc(report), encoding='utf-8')
    return len(items)


def sid_fmt(sid):
    return '#' + sid


def _shift_text(s):
    if not s:
        return ''
    dx, dy = s['dx'], s['dy']
    parts = []
    if dx:
        parts.append(f"가로 {abs(dx)}px {'오른쪽' if dx > 0 else '왼쪽'}")
    if dy:
        parts.append(f"세로 {abs(dy)}px {'아래' if dy > 0 else '위'}")
    msg = ' · '.join(parts)
    return f"변환 결과가 PSD보다 {msg} 어긋남(보정하면 차이 {s['diff_before']}% → {s['diff_after']}%)"


def _markdown(rp):
    L = [f"# PSD 불일치 보고서", '', f"- 전체 일치율: **{rp['match_percent']}%**", f"- 불일치 구간: {rp['region_count']}곳 (차이가 큰 순서)", '',
         '> 구간별 이미지는 `analysis/mismatch/` 폴더에 있습니다. psd = PSD 합성본, page = 변환 결과, diff = 빨간 부분이 다른 곳.', '']
    for it in rp['regions']:
        r = it['region']
        sec = it['section']
        L += [f"## #{it['no']} · 위치 x={r['x']} y={r['y']} · 크기 {r['width']}×{r['height']} · 차이 {it['diff_percent']}%",
              f"- 섹션: {sec['id']} ({sec['psd_group']})" if sec else '- 섹션: (알 수 없음)',
              f"- 점검: {it['hint']}"]
        if it['shift']:
            L.append(f"- 위치: {_shift_text(it['shift'])}")
        if it['html_elements']:
            L.append('- 수정할 HTML/CSS 요소:')
            L += [f"  - `{e['selector']}`  ({e['rect'][0]},{e['rect'][1]} {e['rect'][2]}×{e['rect'][3]})" for e in it['html_elements']]
        if it['psd_layers']:
            L.append('- 관련 PSD 레이어:')
            L += [f"  - {l['id']} [{l['kind']}] {l['name']}  ({l['bbox'][0]},{l['bbox'][1]} {l['bbox'][2]}×{l['bbox'][3]})" for l in it['psd_layers']]
        L += [f"- 이미지: {it['images']['psd']} / {it['images']['page']} / {it['images']['diff']}", '']
    return '\n'.join(L)


def _html_doc(rp):
    e = _html.escape
    cards = []
    for it in rp['regions']:
        r = it['region']
        sec = it['section']
        els = ''.join(f"<li><code>{e(x['selector'])}</code> <span>{x['rect'][0]},{x['rect'][1]} · {x['rect'][2]}×{x['rect'][3]}</span></li>" for x in it['html_elements']) or '<li class="mute">찾지 못했습니다</li>'
        lys = ''.join(f"<li><b>{e(l['id'])}</b> [{e(l['kind'])}] {e(l['name'])} <span>{l['bbox'][0]},{l['bbox'][1]} · {l['bbox'][2]}×{l['bbox'][3]}</span></li>" for l in it['psd_layers']) or '<li class="mute">없음</li>'
        sh = _shift_text(it['shift'])
        cards.append(f"""<section class="card"><h2><span class="no">#{it['no']}</span> {e(sec['id'] + ' · ' + sec['psd_group']) if sec else '구간'} <em>{it['diff_percent']}% 다름</em></h2>
<p class="meta">위치 x={r['x']}, y={r['y']} · 크기 {r['width']}×{r['height']}px</p>
<p class="hint">{e(it['hint'])}</p>{f'<p class="shift">{e(sh)}</p>' if sh else ''}
<div class="imgs"><figure><figcaption>PSD</figcaption><img src="{e(it['images']['psd'])}"></figure><figure><figcaption>변환 결과</figcaption><img src="{e(it['images']['page'])}"></figure><figure><figcaption>차이 (빨강)</figcaption><img src="{e(it['images']['diff'])}"></figure></div>
<div class="cols"><div><h3>수정할 HTML/CSS 요소</h3><ul>{els}</ul></div><div><h3>관련 PSD 레이어</h3><ul>{lys}</ul></div></div></section>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>PSD 불일치 보고서</title><style>
body{{margin:0;background:#f7f7f5;color:#111;font:14px/1.5 'Malgun Gothic',sans-serif}}.wrap{{max-width:1180px;margin:0 auto;padding:32px 24px 60px}}
h1{{font-size:24px;margin:0 0 6px}}.sum{{color:#555;margin:0 0 24px}}.big{{font-size:40px;font-weight:700}}
.card{{background:#fff;border:1px solid #e5e5e2;border-radius:12px;padding:20px;margin:0 0 18px}}.card h2{{font-size:17px;margin:0 0 4px}}.no{{display:inline-block;background:#111;color:#fff;border-radius:6px;padding:0 8px;margin-right:6px}}
.card em{{font-style:normal;color:#dc2626;font-size:13px;margin-left:8px}}.meta{{color:#777;margin:0 0 6px;font-size:12.5px}}.hint{{margin:0 0 4px}}.shift{{margin:0 0 8px;color:#b45309;font-weight:600}}
.imgs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:10px 0}}figure{{margin:0}}figcaption{{font-size:12px;color:#777;margin-bottom:4px}}img{{max-width:100%;border:1px solid #e5e5e2;background:#fafafa}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}h3{{font-size:13px;margin:6px 0}}ul{{margin:0;padding-left:18px}}li{{margin:2px 0}}code{{background:#f2f2ef;padding:1px 5px;border-radius:4px;font-size:12.5px}}li span{{color:#888;font-size:12px}}.mute{{color:#aaa}}
</style></head><body><div class="wrap"><h1>PSD 불일치 보고서</h1><p class="sum">변환 결과를 PSD 합성본과 비교해 다른 구간을 큰 순서로 모았습니다. 이 구간만 고치면 됩니다.</p>
<div class="big">{rp['match_percent']}% 일치</div><p class="sum">불일치 구간 {rp['region_count']}곳</p>{''.join(cards)}</div></body></html>"""
