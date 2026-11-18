"""PHP 결과를 다른 형식으로 한 번 더 내보낸다: 정적 HTML / React(Vite) / Vue(Vite) / 워드프레스 테마 / 그누보드5 테마.
기본 결과(out/)는 그대로 두고 out/targets/<형식>/ 에 따로 만든다."""
import html as _html
import json
import re
import shutil
from pathlib import Path

import enhance as E

LABELS = {'html': '정적 HTML', 'react': 'React', 'vue': 'Vue', 'wordpress': '워드프레스 테마', 'gnuboard': '그누보드5 테마'}


def _rd(p): return Path(p).read_text(encoding='utf-8')


def _wr(p, s):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(s, encoding='utf-8', newline='\n')


def _strip_php(s): return re.sub(r'<\?.*?\?>', '', s, flags=re.S)


class Site:
    """out/ 의 PHP 결과를 읽어 조각으로 나눈다."""

    def __init__(self, out):
        self.out = Path(out)
        head = _rd(self.out / 'inc/head.php')
        self.head_raw = head
        m = re.search(r'<title>(.*?)</title>', head, re.S); self.title = _html.unescape(m.group(1)) if m else 'Pengo'
        hm = re.search(r'<head>(.*)</head>', head, re.S); self.head_inner = hm.group(1) if hm else ''
        nav = _rd(self.out / 'inc/nav.php') if (self.out / 'inc/nav.php').exists() else ''
        top = _rd(self.out / 'inc/top.php').replace('<?php include "nav.php"; ?>', nav)
        self.top = _strip_php(top)
        bottom = _strip_php(_rd(self.out / 'inc/bottom.php'))
        self.bottom = re.sub(r'</body>.*', '', bottom, flags=re.S)
        idx = _rd(self.out / 'index.php')
        m = re.search(r'<!-- Content -->(.*)<!-- //Content -->', idx, re.S)
        self.main = _strip_php(m.group(1)).strip() if m else ''
        # head.php 끝의 <div id="wrap"> 같은 여는 태그는 top 앞으로
        self.after_head = re.sub(r'.*</head>', '', head, flags=re.S)
        self.after_head = re.sub(r'<body[^>]*>', '', _strip_php(self.after_head)).strip()

    def head_links(self):
        """<head> 안의 css·js·글꼴 링크 줄들 (PHP 제거)"""
        return _strip_php(self.head_inner)

    def copy_assets(self, dest, sub_css='css', sub_js='js', public=None):
        for d in ('images', 'fonts', 'js'):
            if (self.out / d).exists(): shutil.copytree(self.out / d, Path(dest) / d, dirs_exist_ok=True)
        if (self.out / 'css').exists(): shutil.copytree(self.out / 'css', Path(dest) / sub_css, dirs_exist_ok=True)


# ───────────────────────── JSX ─────────────────────────
JSX_ATTR = {'class': 'className', 'for': 'htmlFor', 'tabindex': 'tabIndex', 'datetime': 'dateTime', 'colspan': 'colSpan', 'rowspan': 'rowSpan', 'maxlength': 'maxLength',
            'readonly': 'readOnly', 'autocomplete': 'autoComplete', 'crossorigin': 'crossOrigin', 'srcset': 'srcSet', 'frameborder': 'frameBorder', 'allowfullscreen': 'allowFullScreen', 'enctype': 'encType'}


def _style_obj(v):
    items = []
    for part in v.split(';'):
        if ':' not in part: continue
        k, val = part.split(':', 1); k = k.strip(); val = val.strip()
        if k.startswith('--'): key = json.dumps(k)
        else: key = re.sub(r'-([a-z])', lambda m: m.group(1).upper(), k)
        items.append(f'{key}: {json.dumps(val, ensure_ascii=False)}')
    return '{{' + ', '.join(items) + '}}'


def _jsx_text(t):
    t = t.replace('{', '&#123;').replace('}', '&#125;')
    return t.replace('<', '&lt;') if '<' in t else t


def to_jsx(n, depth=0):
    if isinstance(n, str):
        if n.startswith('<!--') or n.startswith('<?'): return ''
        return _jsx_text(n)
    if n.tag == '#root': return ''.join(to_jsx(k) for k in n.kids)
    attrs = ''
    for k, v in n.attrs:
        key = JSX_ATTR.get(k, k)
        if k == 'style' and v is not None: attrs += f' style={_style_obj(v)}'
        elif k.startswith('on'): continue
        elif v is None: attrs += f' {key}'
        else: attrs += f' {key}="{_html.escape(v, quote=True)}"'
    if n.tag in E.VOID: return f'<{n.tag}{attrs} />'
    inner = ''.join(to_jsx(k) for k in n.kids)
    if n.tag == 'textarea': return f'<{n.tag}{attrs} defaultValue="{_html.escape(E.text_of(n), quote=True)}" />'
    return f'<{n.tag}{attrs}>{inner}</{n.tag}>'


INLINE = {'span', 'b', 'a', 'em', 'strong', 'i', 'u', 'small', 'time', 'br', 'img', 'label', 'sup', 'sub', 'button', 'input', 'textarea'}


def _pretty_jsx(s, base=3):
    """태그 사이에만 줄을 나눈다. 글자 앞뒤는 건드리지 않아(공백이 그대로) 화면이 달라지지 않는다."""
    out, lvl, glue, prev_inline = [], 0, True, False
    for tok in re.findall(r'<[^>]+>|[^<]+', s):
        if tok.startswith('<'):
            m = re.match(r'</?([A-Za-z0-9]+)', tok)
            name = m.group(1).lower() if m else ''
            closing = tok.startswith('</')
            selfc = tok.endswith('/>') or name in E.VOID
            inline = name in INLINE
            if closing: lvl = max(0, lvl - 1)
            if out and (glue or (inline and prev_inline)): out[-1] += tok
            else: out.append('  ' * (base + lvl) + tok)
            if not closing and not selfc: lvl += 1
            glue, prev_inline = False, inline
        elif tok.strip():
            tok = tok.replace('\n', ' ')
            if out: out[-1] += tok
            else: out.append('  ' * (base + lvl) + tok.strip())
            glue = True
        elif '\n' not in tok and out:
            out[-1] += tok
            glue = True
        else:
            glue = False
    return '\n'.join(out)


def _css_links(site):
    return re.findall(r'href="(/css/[^"?]+)', site.head_links())


def _external_head(site):
    """CDN 글꼴·스크립트 등 외부 링크만 (index.html 용)"""
    lines = []
    for m in re.finditer(r'<(?:link|script)[^>]*>(?:</script>)?', site.head_links()):
        t = m.group(0)
        if re.search(r'(href|src)="https?://', t) or re.search(r'(href|src)="/js/', t): lines.append(t)
    return '\n'.join(lines)


def _meta_lines(site):
    return '\n'.join(re.findall(r'<meta[^>]+>', site.head_links()))


def export(target, out, title=None):
    site = Site(out)
    fn = {'html': _html_site, 'react': _react, 'vue': _vue, 'wordpress': _wordpress, 'gnuboard': _gnuboard}[target]
    dest = Path(out) / 'targets' / target
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    fn(site, dest)
    return dest


# ───────────────────────── 정적 HTML ─────────────────────────
def _rel(s): return re.sub(r'(href|src)="/(?!/)', r'\1="', s)


def _html_site(site, dest):
    site.copy_assets(dest)
    page = ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + _rel(site.head_links()).strip() + '\n</head>\n<body>\n' + site.after_head + '\n'
            + _rel(site.top) + '\n' + _rel(site.main) + '\n' + _rel(site.bottom) + '\n</body>\n</html>\n')
    page = re.sub(r"url\((['\"]?)/", r'url(\1', page)
    _wr(dest / 'index.html', page)
    for f in (dest / 'css').glob('*.css'):
        t = _rd(f); _wr(f, t.replace('url(/', 'url(../').replace("url('/", "url('../"))
    _wr(dest / 'README.txt', '정적 HTML 형식입니다. index.html 을 열면 됩니다 (서버 없이 동작). 메뉴 링크·폼 action 은 실제 주소로 바꿔 주세요.\n')


# ───────────────────────── React ─────────────────────────
def _comp(name, src):
    body = _pretty_jsx(to_jsx(E.parse(src)), 3)
    return f'export default function {name}() {{\n  return (\n    <>\n{body}\n    </>\n  )\n}}\n'


def _vite_common(site, dest, kind):
    site.copy_assets(dest / 'public', sub_css='css')
    shutil.rmtree(dest / 'public' / 'css', ignore_errors=True)
    (dest / 'src/css').mkdir(parents=True, exist_ok=True)
    for f in (site.out / 'css').glob('*.css'): _wr(dest / 'src/css' / f.name, _rd(f))
    css = [Path(c).name for c in _css_links(site)]
    for f in sorted((site.out / 'css').glob('*.css')):
        if f.name not in css: css.append(f.name)
    ext = _external_head(site)
    meta = _meta_lines(site)
    entry = 'src/main.jsx' if kind == 'react' else 'src/main.js'
    _wr(dest / 'index.html', '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + meta + '\n<title>' + _html.escape(site.title) + '</title>\n' + ext +
        f'\n</head>\n<body>\n<div id="root"></div>\n<script type="module" src="/{entry}"></script>\n</body>\n</html>\n' if kind == 'react' else
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + meta + '\n<title>' + _html.escape(site.title) + '</title>\n' + ext + f'\n</head>\n<body>\n<div id="app"></div>\n<script type="module" src="/{entry}"></script>\n</body>\n</html>\n')
    return css


def _react(site, dest):
    css = _vite_common(site, dest, 'react')
    _wr(dest / 'package.json', json.dumps({'name': 'pengo-site', 'private': True, 'version': '0.0.0', 'type': 'module',
        'scripts': {'dev': 'vite', 'build': 'vite build', 'preview': 'vite preview'},
        'dependencies': {'react': '^18.3.1', 'react-dom': '^18.3.1'}, 'devDependencies': {'@vitejs/plugin-react': '^4.3.1', 'vite': '^5.4.0'}}, indent=2) + '\n')
    _wr(dest / 'vite.config.js', "import { defineConfig } from 'vite'\nimport react from '@vitejs/plugin-react'\n\nexport default defineConfig({ plugins: [react()] })\n")
    imports = ''.join(f"import './css/{c}'\n" for c in css)
    _wr(dest / 'src/main.jsx', "import React from 'react'\nimport { createRoot } from 'react-dom/client'\n" + imports + "import App from './App.jsx'\n\ncreateRoot(document.getElementById('root')).render(<App />)\n")
    _wr(dest / 'src/App.jsx', "import Header from './components/Header.jsx'\nimport Main from './components/Main.jsx'\nimport Footer from './components/Footer.jsx'\n\n"
        "export default function App() {\n  return (\n    <div id=\"wrap\">\n      <Header />\n      <Main />\n      <Footer />\n    </div>\n  )\n}\n")
    _wr(dest / 'src/components/Header.jsx', _comp('Header', site.top))
    _wr(dest / 'src/components/Main.jsx', _comp('Main', site.main))
    _wr(dest / 'src/components/Footer.jsx', _comp('Footer', site.bottom))
    _wr(dest / 'README.txt', 'React(Vite) 프로젝트입니다.\n  npm install\n  npm run dev\nCSS 는 src/css, 이미지·글꼴·js 는 public/ 에 있습니다. 메뉴·슬라이더 등 jQuery 동작은 public/js 를 index.html 에서 불러 쓰거나 React 방식으로 다시 만드세요.\n')


# ───────────────────────── Vue ─────────────────────────
def _vue_html(src):
    return src.replace('{{', '&#123;&#123;').replace('}}', '&#125;&#125;')


def _vue(site, dest):
    css = _vite_common(site, dest, 'vue')
    _wr(dest / 'package.json', json.dumps({'name': 'pengo-site', 'private': True, 'version': '0.0.0', 'type': 'module',
        'scripts': {'dev': 'vite', 'build': 'vite build', 'preview': 'vite preview'},
        'dependencies': {'vue': '^3.4.0'}, 'devDependencies': {'@vitejs/plugin-vue': '^5.1.0', 'vite': '^5.4.0'}}, indent=2) + '\n')
    _wr(dest / 'vite.config.js', "import { defineConfig } from 'vite'\nimport vue from '@vitejs/plugin-vue'\n\nexport default defineConfig({ plugins: [vue()] })\n")
    imports = ''.join(f"import './css/{c}'\n" for c in css)
    _wr(dest / 'src/main.js', "import { createApp } from 'vue'\n" + imports + "import App from './App.vue'\n\ncreateApp(App).mount('#app')\n")
    parts = []
    for name, src in (('Header', site.top), ('Main', site.main), ('Footer', site.bottom)):
        _wr(dest / f'src/components/{name}.vue', '<template>\n' + _pretty_jsx(E.dump(E.parse(_vue_html(src))), 1) + '\n</template>\n')
    _wr(dest / 'src/App.vue', "<script setup>\nimport Header from './components/Header.vue'\nimport Main from './components/Main.vue'\nimport Footer from './components/Footer.vue'\n</script>\n\n"
        "<template>\n  <div id=\"wrap\">\n    <Header />\n    <Main />\n    <Footer />\n  </div>\n</template>\n")
    _wr(dest / 'README.txt', 'Vue 3(Vite) 프로젝트입니다.\n  npm install\n  npm run dev\nCSS 는 src/css, 이미지·글꼴·js 는 public/ 에 있습니다.\n')


# ───────────────────────── 워드프레스 ─────────────────────────
def _slug(t):
    s = re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')
    return s or 'pengo-theme'


def _php_assets(s, base_expr):
    s = re.sub(r'(src|href)="/(images|fonts|js|css)/', lambda m: f'{m.group(1)}="<?php echo {base_expr}; ?>/{m.group(2)}/', s)
    return s


def _fix_css_urls(dest):
    for f in (dest / 'css').glob('*.css'):
        t = _rd(f); _wr(f, t.replace('url(/', 'url(../').replace("url('/", "url('../"))


def _wordpress(site, dest):
    slug = _slug(site.title); theme = dest / slug
    site.copy_assets(theme); _fix_css_urls(theme)
    B = 'get_template_directory_uri()'
    css = [Path(c).name for c in _css_links(site)]
    for f in sorted((theme / 'css').glob('*.css')):
        if f.name not in css: css.append(f.name)
    ext = [m for m in re.findall(r'<link[^>]+href="(https?://[^"]+)"[^>]*>', site.head_links())]
    scripts = [Path(u).name for u in re.findall(r'<script[^>]+src="/js/([^"]+)"', site.head_links())]
    _wr(theme / 'style.css', f'/*\nTheme Name: {site.title}\nDescription: Pengo 가 PSD 에서 만든 테마\nVersion: 1.0\nText Domain: {slug}\n*/\n')
    fx = ''.join(f"    wp_enqueue_style('{slug}-ext{i}', '{u}', array(), null);\n" for i, u in enumerate(ext))
    fc = ''.join(f"    wp_enqueue_style('{slug}-{Path(c).stem}', get_template_directory_uri() . '/css/{c}', array(), '1.0');\n" for c in css)
    fs = ''.join(f"    wp_enqueue_script('{slug}-{Path(sc).stem}', get_template_directory_uri() . '/js/{sc}', array(), '1.0', true);\n" for sc in scripts if 'jquery' not in sc)
    _wr(theme / 'functions.php', "<?php\nif (!defined('ABSPATH')) exit;\n\nadd_action('after_setup_theme', function () {\n    add_theme_support('title-tag');\n    add_theme_support('post-thumbnails');\n    register_nav_menus(array('primary' => '메인 메뉴'));\n});\n\n"
        "add_action('wp_enqueue_scripts', function () {\n" + fx + fc + "    wp_enqueue_script('jquery');\n" + fs + "});\n")
    metas = '\n'.join(m for m in re.findall(r'<meta[^>]+>', site.head_links()) if 'viewport' in m or 'description' in m or 'og:' in m or 'twitter' in m)
    top = _php_assets(site.top, B).replace('href="/"', 'href="<?php echo esc_url(home_url(\'/\')); ?>"')
    _wr(theme / 'header.php', '<!DOCTYPE html>\n<html <?php language_attributes(); ?>>\n<head>\n<meta charset="<?php bloginfo(\'charset\'); ?>">\n' + metas + '\n<?php wp_head(); ?>\n</head>\n<body <?php body_class(); ?>>\n<?php wp_body_open(); ?>\n'
        + (site.after_head + '\n' if site.after_head else '') + top + '\n')
    _wr(theme / 'footer.php', _php_assets(site.bottom, B) + '\n<?php wp_footer(); ?>\n</body>\n</html>\n')
    main = _php_assets(site.main, B)
    _wr(theme / 'front-page.php', '<?php get_header(); ?>\n' + main + '\n<?php get_footer(); ?>\n')
    _wr(theme / 'index.php', '<?php get_header(); ?>\n<main id="content">\n<?php if (have_posts()) : while (have_posts()) : the_post(); ?>\n  <article <?php post_class(); ?>><h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2><?php the_content(); ?></article>\n<?php endwhile; endif; ?>\n</main>\n<?php get_footer(); ?>\n')
    _wr(dest / 'README.txt', f'워드프레스 테마 폴더: {slug}/\n wp-content/themes/ 에 이 폴더를 통째로 넣고 [외모 → 테마]에서 활성화하세요.\n 첫 화면은 front-page.php 입니다. 메뉴는 정적 HTML 이라 wp_nav_menu 로 바꾸려면 header.php 의 메뉴 부분을 교체하세요.\n')


# ───────────────────────── 그누보드5 ─────────────────────────
def _gnuboard(site, dest):
    slug = _slug(site.title); theme = dest / 'theme' / slug
    site.copy_assets(theme); _fix_css_urls(theme)
    U = 'G5_THEME_URL'
    css = [Path(c).name for c in _css_links(site)]
    for f in sorted((theme / 'css').glob('*.css')):
        if f.name not in css: css.append(f.name)
    ext = re.findall(r'<link[^>]+href="(https?://[^"]+)"[^>]*>', site.head_links())
    adds = ''.join(f"add_stylesheet('<link rel=\"stylesheet\" href=\"{u}\">', 0);\n" for u in ext)
    adds += ''.join(f"add_stylesheet('<link rel=\"stylesheet\" href=\"'.G5_THEME_URL.'/css/{c}\">', 0);\n" for c in css)
    top = _php_assets(site.top, U).replace('href="/"', 'href="<?php echo G5_URL; ?>/"')
    _wr(theme / 'head.php', "<?php\nif (!defined('_GNUBOARD_')) exit;\n\ninclude_once(G5_THEME_PATH.'/head.sub.php');\n" + adds + "?>\n" + (site.after_head + '\n' if site.after_head else '') + top + '\n')
    _wr(theme / 'head.sub.php', "<?php\nif (!defined('_GNUBOARD_')) exit;\ninclude_once(G5_PATH.'/head.sub.php');\n")
    _wr(theme / 'tail.php', "<?php\nif (!defined('_GNUBOARD_')) exit;\n?>\n" + _php_assets(site.bottom, U) + "\n<?php\ninclude_once(G5_PATH.'/tail.sub.php');\n")
    main = _php_assets(site.main, U)
    _wr(theme / 'index.php', "<?php\nif (!defined('_INDEX_')) define('_INDEX_', TRUE);\nif (!defined('_GNUBOARD_')) exit;\n\ninclude_once(G5_THEME_PATH.'/head.php');\n?>\n" + main + "\n<?php\ninclude_once(G5_THEME_PATH.'/tail.php');\n")
    _wr(theme / 'readme.txt', f'{site.title} 테마\n')
    _wr(dest / 'README.txt', f'그누보드5 테마 폴더: theme/{slug}/\n 그누보드 theme/ 폴더에 {slug} 폴더를 넣고 관리자 [테마설정]에서 적용하세요.\n 게시판·회원 스킨은 만들지 않습니다. 메뉴 링크와 폼 action 은 실제 주소로 바꿔 주세요.\n 그누보드 버전에 따라 head.sub.php 호출 방식이 다를 수 있습니다.\n')
