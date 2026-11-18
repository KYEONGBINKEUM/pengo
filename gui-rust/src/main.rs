#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use eframe::egui::{
    self, pos2, text::LayoutJob, text::TextFormat, vec2, Align, Align2, Color32, CursorIcon, FontFamily, FontId, Layout, Margin, Rect,
    RichText, Rounding, Sense, Stroke, Ui,
};
use std::io::{BufRead, BufReader};
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// 업데이트를 배포하는 GitHub 저장소 (배포 전용 공개 저장소). 릴리스에 올린 setup.exe 를 내려받는다.
const UPDATE_REPO: &str = "KYEONGBINKEUM/pengo";

#[derive(Clone)]
struct UpdateInfo {
    version: String,
    url: String,
    sha_url: Option<String>,
}

// ---- 팔레트: 흰색 + 검정 한 가지 강조색 (장식 최소화) ----
const BG: Color32 = Color32::from_rgb(11, 11, 13);
const ACCENT: Color32 = Color32::from_rgb(200, 255, 77);
const ON_ACCENT: Color32 = Color32::from_rgb(14, 16, 6);
const PANEL: Color32 = Color32::from_rgb(22, 22, 26);
const INK: Color32 = Color32::from_rgb(244, 244, 245);
const SUB: Color32 = Color32::from_rgb(142, 142, 151);
const FAINT: Color32 = Color32::from_rgb(96, 96, 104);
const LINE: Color32 = Color32::from_rgb(40, 40, 46);
const TRACK: Color32 = Color32::from_rgb(30, 30, 35);
const OK: Color32 = Color32::from_rgb(74, 222, 128);
const ERR: Color32 = Color32::from_rgb(248, 113, 113);
const TERM_BG: Color32 = Color32::from_rgb(8, 8, 10);

const QUALITIES: [(&str, &str, &str); 5] = [
    ("최고 화질", "lossless", "WebP 무손실 · 용량 큼"),
    ("PNG", "png", "PNG 무손실"),
    ("높음", "high", "WebP 95"),
    ("보통", "normal", "WebP 85 · 용량 작음"),
    ("자동", "auto", "사진은 작게 · 그래픽은 선명하게"),
];
/// 다른 형식으로도 내보내기 (엔진 --target 값, 화면 이름)
const TARGETS: [(&str, &str); 5] = [("html", "정적 HTML"), ("react", "React"), ("vue", "Vue"), ("wordpress", "워드프레스 테마"), ("gnuboard", "그누보드5 테마")];
const SCALES: [(&str, &str); 3] = [("1배", "PSD 크기 그대로"), ("2배", "고해상도용 · 코드는 동일"), ("3배", "초고해상도용")];
const CSS_ROUNDS: [(&str, &str, &str); 2] = [("깔끔하게", "tidy", "5px·2px 단위로 정리"), ("정확하게", "exact", "PSD 값에 가깝게")];
const STAGES: [(&str, &str, f32); 4] = [("분석", "", 0.40), ("변환", "", 0.82), ("작성", "", 0.97), ("압축", "", 1.01)];

enum Msg {
    UpdateFound(UpdateInfo),
    UpdateNote(String),
    UpdateProgress(f32),
    UpdateFailed(String),
    UpdateReady(PathBuf),
    Progress(f32, String),
    Log(String),
    Match(f32),
    Mismatch(usize),
    Done(bool, PathBuf),
}

#[derive(PartialEq, Clone, Copy)]
enum Phase {
    Idle,
    Running,
    Done,
    Failed,
    Cancelled,
}

struct App {
    psd: String,
    zip: String,
    // recipe: String,   // 반복 구조 레시피 (현재 화면에서 숨김 — 필요하면 아래 주석을 해제)
    out: String,
    structure: bool,
    quality: usize,
    img_scale: usize,
    css_round: usize,
    a11y: bool,
    repeat: bool,
    forms: bool,
    targets: [bool; 5],
    presets: Vec<String>,
    preset_name: String,
    preset_msg: String,
    feed: Vec<(String, String, bool)>, // (시간, 내용, 엔진 로그 여부)
    step: String,
    target: f32,
    shown: f32,
    phase: Phase,
    started: Option<Instant>,
    elapsed: Duration,
    last_out: Option<PathBuf>,
    zip_out: Option<PathBuf>,
    match_pct: Option<f32>,
    mismatch_n: usize,
    update: Option<UpdateInfo>,
    upd_state: u8, // 0 대기, 1 내려받는 중, 2 실패/메시지
    upd_progress: f32,
    upd_msg: String,
    upd_note: String,
    advanced: bool,
    page: usize,
    pv_tab: usize,
    show_log: bool,
    tex_page: Option<egui::TextureHandle>,
    tex_psd: Option<egui::TextureHandle>,
    tex_logo: Option<egui::TextureHandle>,
    settings: bool,
    rule_vals: Vec<String>,
    set_msg: String,
    confirm_reset: bool,
    cancelled: bool,
    autostart: bool,
    pid: Arc<AtomicU32>,
    tx: Sender<Msg>,
    rx: Receiver<Msg>,
}

fn app_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// 저장 위치 기본값: 내 문서\PSD Publisher (설치 폴더에 결과가 섞이지 않게)
fn default_out_dir() -> String {
    match std::env::var("USERPROFILE") {
        Ok(h) => PathBuf::from(h).join("Documents").join("PSD Publisher").to_string_lossy().into_owned(),
        Err(_) => app_dir().join("generated").to_string_lossy().into_owned(),
    }
}

/// 변환 규칙 항목: (키, 이름, 기본값, 숫자 여부)
const RULES: &[(&str, &str, &str, bool)] = &[
    ("inner", "컨테이너 폭 (px)", "auto", true),
    ("wide", "넓은 컨테이너 폭 (px)", "auto", true),
    ("box_class", "컨테이너 클래스", "inner", false),
    ("wide_class", "넓은 컨테이너 클래스", "w-inner", false),
    ("header_id", "헤더 id", "header", false),
    ("content_id", "본문 id", "content", false),
    ("footer_id", "푸터 id", "footer", false),
    ("quick_id", "퀵메뉴 id", "quick", false),
    ("visual_id", "첫 섹션 id", "mVisual", false),
    ("section_prefix", "섹션 id 접두어", "sec", false),
    ("left", "왼쪽 칸 클래스", "l_cont", false),
    ("center", "가운데 칸 클래스", "c_cont", false),
    ("right", "오른쪽 칸 클래스", "r_cont", false),
    ("text_top", "글자 묶음 클래스 (섹션)", "m_txt", false),
    ("text_card", "글자 묶음 클래스 (카드)", "txt", false),
    ("image_path", "이미지 경로", "/images/", false),
];

/// 내 기본틀 폴더: %APPDATA%\Pengo\frame  (있으면 변환에 사용, 없으면 내장 회사 기본틀)
fn frame_dir() -> PathBuf {
    match std::env::var("APPDATA") {
        Ok(a) => PathBuf::from(a).join("Pengo").join("frame"),
        Err(_) => app_dir().join("frame"),
    }
}

fn frame_exists() -> bool {
    frame_dir().join("pengo-rules.json").is_file()
}

/// 내장 회사 기본틀을 편집 가능한 폴더로 꺼낸다 (이미 있으면 그대로 둔다).
fn export_frame() -> Result<(), String> {
    if frame_exists() {
        return Ok(());
    }
    let engine = find_engine().ok_or("변환 엔진을 찾을 수 없습니다.")?;
    let out = Command::new(engine).arg("export-frame").arg("--out").arg(frame_dir()).creation_flags(CREATE_NO_WINDOW).output().map_err(|e| e.to_string())?;
    if out.status.success() && frame_exists() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).lines().last().unwrap_or("기본틀을 꺼내지 못했습니다.").to_string())
    }
}

fn read_rules() -> Vec<String> {
    let cur: serde_json::Value = std::fs::read_to_string(frame_dir().join("pengo-rules.json")).ok().and_then(|t| serde_json::from_str(t.trim_start_matches('\u{feff}')).ok()).unwrap_or(serde_json::Value::Null);
    RULES
        .iter()
        .map(|(k, _, d, _)| match cur.get(*k) {
            Some(serde_json::Value::String(v)) => v.clone(),
            Some(serde_json::Value::Number(n)) => n.to_string(),
            _ => d.to_string(),
        })
        .collect()
}

fn write_rules(vals: &[String]) -> Result<(), String> {
    export_frame()?;
    let path = frame_dir().join("pengo-rules.json");
    let mut obj: serde_json::Map<String, serde_json::Value> = std::fs::read_to_string(&path).ok().and_then(|t| serde_json::from_str(t.trim_start_matches('\u{feff}')).ok()).unwrap_or_default();
    for ((k, _, d, num), v) in RULES.iter().zip(vals) {
        let v = v.trim();
        let v = if v.is_empty() { d } else { v };
        let val = if *num && v.eq_ignore_ascii_case("auto") { serde_json::Value::from("auto") } else if *num { v.parse::<i64>().map(serde_json::Value::from).unwrap_or_else(|_| serde_json::Value::from(*d)) } else { serde_json::Value::from(v) };
        obj.insert(k.to_string(), val);
    }
    std::fs::write(&path, serde_json::to_string_pretty(&obj).unwrap_or_default()).map_err(|e| e.to_string())
}

/// 톱니바퀴 아이콘 (글꼴에 의존하지 않고 직접 그린다)
fn draw_gear(p: &egui::Painter, c: egui::Pos2, col: Color32) {
    let st = Stroke::new(2.2, col);
    for i in 0..8 {
        let a = i as f32 * std::f32::consts::TAU / 8.0;
        let d = vec2(a.cos(), a.sin());
        p.line_segment([c + d * 8.5, c + d * 11.5], Stroke::new(3.6, col));
    }
    p.circle_stroke(c, 8.0, st);
    p.circle_stroke(c, 3.0, Stroke::new(2.0, col));
}

fn presets_dir() -> PathBuf {
    PathBuf::from(std::env::var("APPDATA").unwrap_or_else(|_| ".".into())).join("Pengo").join("presets")
}

fn list_presets() -> Vec<String> {
    let mut v: Vec<String> = std::fs::read_dir(presets_dir())
        .map(|d| d.flatten().filter_map(|e| e.path().file_stem().map(|s| s.to_string_lossy().into_owned()).filter(|_| e.path().extension().map(|x| x == "json").unwrap_or(false))).collect())
        .unwrap_or_default();
    v.sort();
    v
}

fn preset_file(name: &str) -> PathBuf {
    let safe: String = name.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' || c == ' ' { c } else { '_' }).collect();
    presets_dir().join(format!("{}.json", safe.trim()))
}

fn find_engine() -> Option<PathBuf> {
    let d = app_dir();
    let candidates = [
        d.join("engine").join("publisher-engine.exe"),
        d.join("..").join("..").join("..").join("dist").join("publisher-engine").join("publisher-engine.exe"),
    ];
    candidates.into_iter().find(|p| p.is_file())
}

fn bold(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name("bold".into()))
}

fn setup_style(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let regular = std::fs::read(r"C:\Windows\Fonts\malgun.ttf").ok();
    let boldf = std::fs::read(r"C:\Windows\Fonts\malgunbd.ttf").ok();
    if let Some(b) = regular.clone() {
        fonts.font_data.insert("kr".into(), egui::FontData::from_owned(b));
        for fam in [FontFamily::Proportional, FontFamily::Monospace] {
            fonts.families.entry(fam).or_default().push("kr".into()); // 영문·숫자는 기본 글꼴, 한글은 맑은 고딕
        }
    }
    match boldf.or(regular) {
        Some(b) => {
            fonts.font_data.insert("kr_bold".into(), egui::FontData::from_owned(b));
            fonts.families.insert(FontFamily::Name("bold".into()), vec!["kr_bold".into()]);
        }
        None => {
            fonts.families.insert(FontFamily::Name("bold".into()), vec![]);
        }
    }
    ctx.set_fonts(fonts);
    let mut style = (*ctx.style()).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = BG;
    style.visuals.override_text_color = Some(INK);
    style.visuals.extreme_bg_color = Color32::from_rgb(16, 16, 19);
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, LINE);
    for w in [&mut style.visuals.widgets.inactive, &mut style.visuals.widgets.hovered, &mut style.visuals.widgets.active] {
        w.rounding = Rounding::same(8.0);
        w.bg_stroke = Stroke::new(1.0, LINE);
    }
    style.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, Color32::from_rgb(90, 90, 100));
    style.visuals.selection.bg_fill = ACCENT;
    style.visuals.selection.stroke = Stroke::new(1.0, ON_ACCENT);
    style.spacing.item_spacing = vec2(8.0, 10.0);
    style.text_styles.insert(egui::TextStyle::Body, FontId::new(14.0, FontFamily::Proportional));
    style.text_styles.insert(egui::TextStyle::Button, FontId::new(14.0, FontFamily::Proportional));
    style.text_styles.insert(egui::TextStyle::Monospace, FontId::new(12.5, FontFamily::Monospace));
    ctx.set_style(style);
}

fn mix(a: Color32, b: Color32, t: f32) -> Color32 {
    let f = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t).round() as u8;
    Color32::from_rgb(f(a.r(), b.r()), f(a.g(), b.g()), f(a.b(), b.b()))
}

fn panel<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> R {
    egui::Frame::none()
        .fill(PANEL)
        .stroke(Stroke::new(1.0, LINE))
        .rounding(12.0)
        .inner_margin(Margin::same(20.0))
        .show(ui, |ui| add(ui))
        .inner
}

fn caption(ui: &mut Ui, t: &str) {
    ui.label(RichText::new(t).size(12.5).color(SUB));
}

fn field_label(ui: &mut Ui, t: &str) {
    ui.label(RichText::new(t).font(bold(13.5)).color(INK));
}

fn fmt_dur(d: Duration) -> String {
    let s = d.as_secs();
    format!("{}:{:02}", s / 60, s % 60)
}

/// 한 줄로 잘라(…) 그리기
fn paint_trunc(ui: &Ui, pos: egui::Pos2, text: &str, font: FontId, color: Color32, width: f32) {
    let mut job = LayoutJob::single_section(text.to_owned(), TextFormat { font_id: font, color, ..Default::default() });
    job.wrap.max_width = width;
    job.wrap.max_rows = 1;
    job.wrap.break_anywhere = true;
    job.wrap.overflow_character = Some('…');
    let galley = ui.fonts(|f| f.layout_job(job));
    ui.painter().galley(pos, galley, color);
}

/// 면이 채워진 버튼
fn solid_btn(ui: &mut Ui, label: &str, enabled: bool, w: f32, h: f32, fill: Color32) -> bool {
    let (rect, resp) = ui.allocate_exact_size(vec2(w, h), if enabled { Sense::click() } else { Sense::hover() });
    let bg = if !enabled { Color32::from_rgb(34, 34, 40) } else if resp.hovered() { mix(fill, Color32::WHITE, 0.25) } else { fill };
    ui.painter().rect_filled(rect, Rounding::same(h / 2.0), bg);
    ui.painter().text(rect.center(), Align2::CENTER_CENTER, label, bold(15.0), if enabled { ON_ACCENT } else { FAINT });
    if enabled && resp.hovered() {
        ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
    }
    enabled && resp.clicked()
}

/// 테두리만 있는 버튼
fn line_btn(ui: &mut Ui, label: &str, w: f32, h: f32, color: Color32) -> bool {
    let (rect, resp) = ui.allocate_exact_size(vec2(w, h), Sense::click());
    let bg = if resp.hovered() { Color32::from_rgb(32, 32, 38) } else { PANEL };
    ui.painter().rect(rect, Rounding::same(h / 2.0), bg, Stroke::new(1.0, if resp.hovered() { Color32::from_rgb(90, 90, 100) } else { Color32::from_rgb(52, 52, 60) }));
    ui.painter().text(rect.center(), Align2::CENTER_CENTER, label, bold(14.0), color);
    if resp.hovered() {
        ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
    }
    resp.clicked()
}

/// 분할(세그먼트) 선택: 회색 트랙 위에 선택 항목만 흰색으로 떠 있는 형태
fn segmented(ui: &mut Ui, salt: &str, cur: &mut usize, labels: &[&str]) {
    let w = ui.available_width();
    let h = 38.0;
    let (rect, _) = ui.allocate_exact_size(vec2(w, h), Sense::hover());
    ui.painter().rect_filled(rect, Rounding::same(h / 2.0), TRACK);
    let seg = w / labels.len() as f32;
    for (i, l) in labels.iter().enumerate() {
        let r = Rect::from_min_size(pos2(rect.left() + seg * i as f32, rect.top()), vec2(seg, h)).shrink(3.0);
        let resp = ui.interact(r, ui.id().with((salt, i)), Sense::click());
        let sel = *cur == i;
        if sel {
            ui.painter().rect_filled(r, Rounding::same(r.height() / 2.0), ACCENT);
        } else if resp.hovered() {
            ui.painter().rect_filled(r, Rounding::same(r.height() / 2.0), Color32::from_rgb(42, 42, 49));
            ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
        }
        ui.painter().text(r.center(), Align2::CENTER_CENTER, *l, if sel { bold(14.0) } else { FontId::new(14.0, FontFamily::Proportional) }, if sel { ON_ACCENT } else { SUB });
        if resp.clicked() {
            *cur = i;
        }
    }
}

// ================= 업데이트 (GitHub 릴리스) =================
fn parse_ver(s: &str) -> Vec<u32> {
    let mut v: Vec<u32> = s
        .trim_start_matches(|c| c == 'v' || c == 'V')
        .split('.')
        .map(|x| x.chars().take_while(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0))
        .collect();
    while v.len() < 3 {
        v.push(0);
    }
    v
}

fn is_newer(a: &str, b: &str) -> bool {
    parse_ver(a) > parse_ver(b)
}

fn user_agent() -> String {
    format!("PSD-Publisher/{}", env!("CARGO_PKG_VERSION"))
}

/// 최신 릴리스 확인. 새 버전이 있으면 Some. 시험용으로 PSDPUB_UPDATE_URL 로 주소를 바꿀 수 있다.
fn check_update() -> Result<Option<UpdateInfo>, String> {
    let test = std::env::var("PSDPUB_UPDATE_URL").ok();
    let url = test.clone().unwrap_or_else(|| format!("https://api.github.com/repos/{UPDATE_REPO}/releases/latest"));
    let resp = ureq::get(&url)
        .set("User-Agent", &user_agent())
        .set("Accept", "application/vnd.github+json")
        .timeout(Duration::from_secs(8))
        .call()
        .map_err(|e| e.to_string())?;
    let body = resp.into_string().map_err(|e| e.to_string())?;
    let v: serde_json::Value = serde_json::from_str(&body).map_err(|e| e.to_string())?;
    let tag = v["tag_name"].as_str().ok_or("tag_name 없음")?;
    if !is_newer(tag, env!("CARGO_PKG_VERSION")) {
        return Ok(None);
    }
    let assets = v["assets"].as_array().ok_or("assets 없음")?;
    let find = |ext: &str| assets.iter().find(|a| a["name"].as_str().map(|n| n.ends_with(ext)).unwrap_or(false));
    let exe = find(".exe").ok_or("설치 파일이 릴리스에 없습니다")?;
    let url = exe["browser_download_url"].as_str().ok_or("다운로드 주소 없음")?.to_string();
    // 안전: 공식 GitHub 주소가 아니면 거부 (시험용 주소를 쓸 때만 예외)
    if test.is_none() && !url.starts_with("https://github.com/") {
        return Err("신뢰할 수 없는 다운로드 주소".into());
    }
    let sha_url = find(".sha256").and_then(|a| a["browser_download_url"].as_str()).map(String::from);
    Ok(Some(UpdateInfo { version: tag.trim_start_matches(|c| c == 'v' || c == 'V').to_string(), url, sha_url }))
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    h.finalize().iter().map(|b| format!("{:02x}", b)).collect()
}

/// 설치 파일을 내려받아 체크섬을 확인한다. 체크섬 파일이 없거나 다르면 설치하지 않는다.
fn download_update(info: &UpdateInfo, tx: &Sender<Msg>, ctx: &egui::Context) -> Result<PathBuf, String> {
    use std::io::Read;
    let sha_url = info.sha_url.clone().ok_or("체크섬 파일(.sha256)이 릴리스에 없어서 설치하지 않습니다")?;
    let path = std::env::temp_dir().join(format!("PSD-Publisher-Setup-{}.exe", info.version));
    let resp = ureq::get(&info.url).set("User-Agent", &user_agent()).timeout(Duration::from_secs(600)).call().map_err(|e| e.to_string())?;
    let total: f32 = resp.header("Content-Length").and_then(|v| v.parse().ok()).unwrap_or(0.0);
    let mut reader = resp.into_reader();
    let mut data: Vec<u8> = Vec::new();
    let mut buf = [0u8; 65536];
    let mut last = Instant::now();
    loop {
        let n = reader.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        data.extend_from_slice(&buf[..n]);
        if total > 0.0 && last.elapsed() > Duration::from_millis(120) {
            let _ = tx.send(Msg::UpdateProgress(data.len() as f32 / total));
            ctx.request_repaint();
            last = Instant::now();
        }
    }
    let expected = ureq::get(&sha_url).set("User-Agent", &user_agent()).timeout(Duration::from_secs(30)).call().map_err(|e| e.to_string())?
        .into_string().map_err(|e| e.to_string())?;
    let expected = expected.split_whitespace().next().unwrap_or("").to_lowercase();
    if expected.len() != 64 || sha256_hex(&data) != expected {
        return Err("내려받은 파일의 체크섬이 맞지 않아 설치하지 않았습니다".into());
    }
    std::fs::write(&path, &data).map_err(|e| e.to_string())?;
    Ok(path)
}

fn handle_line(line: &str, tx: &Sender<Msg>) {
    if let Some(v) = line.strip_prefix("@@MISMATCH ") {
        let _ = tx.send(Msg::Mismatch(v.trim().parse().unwrap_or(0)));
    } else if let Some(v) = line.strip_prefix("@@MATCH ") {
        let _ = tx.send(Msg::Match(v.trim().parse().unwrap_or(-1.0)));
    } else if let Some(rest) = line.strip_prefix("@@PROGRESS ") {
        let mut it = rest.splitn(2, ' ');
        let pct: f32 = it.next().and_then(|x| x.parse().ok()).unwrap_or(-1.0);
        let msg = it.next().unwrap_or("").to_string();
        let _ = tx.send(Msg::Progress(pct / 100.0, msg));
    } else {
        let _ = tx.send(Msg::Log(format!("{line}\n")));
    }
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        setup_style(&cc.egui_ctx);
        let (tx, rx) = channel();
        if std::env::var("PSDPUB_NO_UPDATE").is_err() {
            // 시작할 때 한 번 조용히 확인 (새 버전이 있을 때만 알림)
            let (txc, ctxc) = (tx.clone(), cc.egui_ctx.clone());
            std::thread::spawn(move || {
                if let Ok(Some(info)) = check_update() {
                    let _ = txc.send(Msg::UpdateFound(info));
                    ctxc.request_repaint();
                }
            });
        }
        Self {
            psd: std::env::var("PSDPUB_PSD").unwrap_or_default(),
            zip: String::new(),
            out: std::env::var("PSDPUB_OUT").unwrap_or_else(|_| default_out_dir()),
            structure: true,
            quality: 0,
            img_scale: 0,
            css_round: 0,
            a11y: true,
            repeat: true,
            forms: true,
            targets: [false; 5],
            presets: list_presets(),
            preset_name: String::new(),
            preset_msg: String::new(),
            feed: Vec::new(),
            step: String::new(),
            target: 0.0,
            shown: 0.0,
            phase: Phase::Idle,
            started: None,
            elapsed: Duration::ZERO,
            last_out: None,
            zip_out: None,
            match_pct: None,
            mismatch_n: 0,
            update: None,
            upd_state: 0,
            upd_progress: 0.0,
            upd_msg: String::new(),
            upd_note: String::new(),
            advanced: false,
            page: 0,
            pv_tab: 0,
            show_log: false,
            tex_page: None,
            tex_psd: None,
            tex_logo: None,
            settings: false,
            rule_vals: Vec::new(),
            set_msg: String::new(),
            confirm_reset: false,
            cancelled: false,
            autostart: std::env::var("PSDPUB_AUTOSTART").is_ok(),
            pid: Arc::new(AtomicU32::new(0)),
            tx,
            rx,
        }
    }

    fn start_update(&mut self, ctx: &egui::Context) {
        let Some(info) = self.update.clone() else { return };
        self.upd_state = 1;
        self.upd_progress = 0.0;
        let (tx, ctx) = (self.tx.clone(), ctx.clone());
        std::thread::spawn(move || {
            match download_update(&info, &tx, &ctx) {
                Ok(p) => {
                    let _ = tx.send(Msg::UpdateReady(p));
                }
                Err(e) => {
                    let _ = tx.send(Msg::UpdateFailed(e));
                }
            }
            ctx.request_repaint();
        });
    }

    fn check_update_manual(&mut self, ctx: &egui::Context) {
        self.upd_note = "확인하는 중…".into();
        let (tx, ctx) = (self.tx.clone(), ctx.clone());
        std::thread::spawn(move || {
            match check_update() {
                Ok(Some(info)) => {
                    let _ = tx.send(Msg::UpdateFound(info));
                }
                Ok(None) => {
                    let _ = tx.send(Msg::UpdateNote("최신 버전입니다".into()));
                }
                Err(_) => {
                    let _ = tx.send(Msg::UpdateNote("확인하지 못했어요 (인터넷 연결을 확인해 주세요)".into()));
                }
            }
            ctx.request_repaint();
        });
    }

    fn ui_update_banner(&mut self, ui: &mut Ui, ctx: &egui::Context) {
        let Some(info) = self.update.clone() else { return };
        let running = self.phase == Phase::Running;
        egui::Frame::none().fill(Color32::from_rgb(30, 34, 20)).stroke(Stroke::new(1.0, Color32::from_rgb(70, 86, 30))).rounding(14.0).inner_margin(Margin::symmetric(16.0, 12.0)).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
                ui.vertical(|ui| {
                    ui.spacing_mut().item_spacing.y = 2.0;
                    ui.label(RichText::new(format!("새 버전 {}이 있어요", info.version)).font(bold(14.5)).color(ACCENT));
                    let sub = match self.upd_state {
                        1 => format!("내려받는 중… {}%", (self.upd_progress * 100.0).round() as i32),
                        2 => self.upd_msg.clone(),
                        _ => "업데이트하면 프로그램이 자동으로 다시 시작돼요".to_string(),
                    };
                    let col = if self.upd_state == 2 { Color32::from_rgb(252, 165, 165) } else { Color32::from_rgb(190, 190, 190) };
                    ui.add(egui::Label::new(RichText::new(sub).size(12.5).color(col)).truncate());
                });
                ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                    if self.upd_state != 1 && !running && line_btn(ui, "업데이트", 92.0, 36.0, INK) {
                        self.start_update(ctx);
                    }
                });
            });
        });
    }

    fn push_feed(&mut self, msg: &str, is_log: bool) {
        let t = fmt_dur(self.elapsed);
        if self.feed.last().map(|l| l.1 == msg).unwrap_or(false) {
            return;
        }
        self.feed.push((t, msg.to_string(), is_log));
        if self.feed.len() > 400 {
            self.feed.remove(0);
        }
    }

    fn start(&mut self, ctx: &egui::Context) {
        let psd = PathBuf::from(&self.psd);
        if !psd.is_file() {
            return;
        }
        let Some(engine) = find_engine() else {
            self.phase = Phase::Failed;
            self.step = "변환 엔진(engine\\publisher-engine.exe)을 찾을 수 없습니다.".into();
            return;
        };
        let stem = psd.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_else(|| "out".into());
        let out = PathBuf::from(&self.out).join(format!("{}-{}", stem, chrono::Local::now().format("%Y%m%d-%H%M%S")));
        let mut cmd = Command::new(engine);
        cmd.arg("build").arg(&psd).arg("--out").arg(&out);
        if self.structure {
            cmd.arg("--structure");
            cmd.arg("--image-quality").arg(QUALITIES[self.quality].1);
            cmd.arg("--image-scale").arg((self.img_scale + 1).to_string());
            cmd.arg("--css-round").arg(CSS_ROUNDS[self.css_round].1);
            if !self.a11y {
                cmd.arg("--no-a11y");
            }
            if !self.repeat {
                cmd.arg("--no-repeat");
            }
            if !self.forms {
                cmd.arg("--no-forms");
            }
            for (i, on) in self.targets.iter().enumerate() {
                if *on {
                    cmd.arg("--target").arg(TARGETS[i].0);
                }
            }
        }
        if frame_exists() {
            cmd.arg("--frame").arg(frame_dir());
        }
        if !self.zip.is_empty() {
            cmd.arg("--source-zip").arg(&self.zip);
        }
        // if !self.recipe.is_empty() { cmd.arg("--recipe").arg(&self.recipe); }   // 반복 구조 레시피 (숨김)
        cmd.env("PYTHONIOENCODING", "utf-8").stdout(Stdio::piped()).stderr(Stdio::piped()).creation_flags(CREATE_NO_WINDOW);
        self.phase = Phase::Running;
        self.page = 2;
        self.show_log = false;
        self.cancelled = false;
        self.feed.clear();
        self.step = "시작하는 중".into();
        self.target = 0.0;
        self.shown = 0.0;
        self.started = Some(Instant::now());
        self.elapsed = Duration::ZERO;
        self.zip_out = None;
        self.last_out = None;
        self.match_pct = None;
        self.mismatch_n = 0;
        self.push_feed("변환을 시작합니다", false);
        let tx = self.tx.clone();
        let pid = self.pid.clone();
        let ctx = ctx.clone();
        std::thread::spawn(move || {
            match cmd.spawn() {
                Ok(mut child) => {
                    pid.store(child.id(), Ordering::SeqCst);
                    let stderr = child.stderr.take();
                    let (tx2, ctx2) = (tx.clone(), ctx.clone());
                    let t = stderr.map(|e| {
                        std::thread::spawn(move || {
                            for line in BufReader::new(e).split(b'\n').flatten() {
                                handle_line(String::from_utf8_lossy(&line).trim_end_matches('\r'), &tx2);
                                ctx2.request_repaint();
                            }
                        })
                    });
                    if let Some(o) = child.stdout.take() {
                        for line in BufReader::new(o).split(b'\n').flatten() {
                            handle_line(String::from_utf8_lossy(&line).trim_end_matches('\r'), &tx);
                            ctx.request_repaint();
                        }
                    }
                    if let Some(t) = t {
                        let _ = t.join();
                    }
                    let ok = child.wait().map(|s| s.success()).unwrap_or(false);
                    pid.store(0, Ordering::SeqCst);
                    let _ = tx.send(Msg::Done(ok, out));
                }
                Err(e) => {
                    let _ = tx.send(Msg::Log(format!("실행 오류: {e}\n")));
                    let _ = tx.send(Msg::Done(false, out));
                }
            }
            ctx.request_repaint();
        });
    }

    fn preset_json(&self) -> serde_json::Value {
        serde_json::json!({
            "quality": self.quality, "img_scale": self.img_scale, "css_round": self.css_round, "structure": self.structure,
            "a11y": self.a11y, "repeat": self.repeat, "forms": self.forms, "targets": self.targets.to_vec(),
        })
    }

    fn apply_preset(&mut self, v: &serde_json::Value) {
        let idx = |k: &str, max: usize, cur: usize| v.get(k).and_then(|x| x.as_u64()).map(|x| (x as usize).min(max)).unwrap_or(cur);
        self.quality = idx("quality", QUALITIES.len() - 1, self.quality);
        self.img_scale = idx("img_scale", SCALES.len() - 1, self.img_scale);
        self.css_round = idx("css_round", CSS_ROUNDS.len() - 1, self.css_round);
        let b = |k: &str, cur: bool| v.get(k).and_then(|x| x.as_bool()).unwrap_or(cur);
        self.structure = b("structure", self.structure);
        self.a11y = b("a11y", self.a11y);
        self.repeat = b("repeat", self.repeat);
        self.forms = b("forms", self.forms);
        if let Some(a) = v.get("targets").and_then(|x| x.as_array()) {
            for (i, t) in self.targets.iter_mut().enumerate() {
                *t = a.get(i).and_then(|x| x.as_bool()).unwrap_or(false);
            }
        }
    }

    fn cancel(&mut self) {
        let pid = self.pid.load(Ordering::SeqCst);
        if pid != 0 {
            self.cancelled = true;
            let _ = Command::new("taskkill").args(["/PID", &pid.to_string(), "/T", "/F"]).creation_flags(CREATE_NO_WINDOW).spawn();
        }
    }

    fn pick_psd(&mut self) {
        if let Some(p) = rfd::FileDialog::new().add_filter("Photoshop", &["psd", "psb"]).pick_file() {
            self.psd = p.to_string_lossy().into_owned();
            self.phase = Phase::Idle;
            self.feed.clear();
            self.target = 0.0;
            self.shown = 0.0;
        }
    }

    // ================= 공통 =================
    fn has_psd(&self) -> bool {
        PathBuf::from(&self.psd).is_file()
    }

    fn load_previews(&mut self, ctx: &egui::Context) {
        self.tex_page = None;
        self.tex_psd = None;
        let Some(o) = self.last_out.clone() else { return };
        let load = |name: &str, file: &str| -> Option<egui::TextureHandle> {
            let img = image::open(o.join("analysis").join(file)).ok()?.to_rgba8();
            let size = [img.width() as usize, img.height() as usize];
            Some(ctx.load_texture(name, egui::ColorImage::from_rgba_unmultiplied(size, img.as_raw()), egui::TextureOptions::LINEAR))
        };
        self.tex_page = load("pv_page", "result-preview.jpg");
        self.tex_psd = load("pv_psd", "reference-preview.jpg");
    }

    fn reset_all(&mut self) {
        self.psd.clear();
        self.phase = Phase::Idle;
        self.page = 0;
        self.feed.clear();
        self.target = 0.0;
        self.shown = 0.0;
        self.tex_page = None;
        self.tex_psd = None;
        self.last_out = None;
        self.zip_out = None;
        self.match_pct = None;
        self.mismatch_n = 0;
    }

    fn ui_header(&mut self, ui: &mut Ui) {
        ui.horizontal_centered(|ui| {
            // 왼쪽 위: 설정(톱니바퀴)
            let running = self.phase == Phase::Running;
            let (r, resp) = ui.allocate_exact_size(vec2(38.0, 38.0), Sense::click());
            let resp = resp.on_hover_cursor(if running { CursorIcon::NotAllowed } else { CursorIcon::PointingHand });
            let col = if self.settings { ACCENT } else if resp.hovered() && !running { INK } else { SUB };
            if self.settings || (resp.hovered() && !running) {
                ui.painter().circle_filled(r.center(), 19.0, PANEL);
            }
            draw_gear(ui.painter(), r.center(), col);
            if resp.clicked() && !running {
                if self.settings {
                    self.settings = false;
                } else {
                    self.settings = true;
                    self.rule_vals = read_rules();
                    self.set_msg.clear();
                    self.confirm_reset = false;
                }
            }
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.horizontal(|ui| {
                    ui.spacing_mut().item_spacing.x = 8.0;
                    let labels = ["파일", "옵션", "변환", "결과"];
                    for (i, l) in labels.iter().enumerate().rev() {
                        let col = if i <= self.page { INK } else { FAINT };
                        ui.label(RichText::new(*l).font(if i == self.page { bold(14.0) } else { FontId::new(14.0, FontFamily::Proportional) }).color(col));
                        let (r, _) = ui.allocate_exact_size(vec2(24.0, 24.0), Sense::hover());
                        let c = r.center();
                        if i < self.page {
                            ui.painter().circle_filled(c, 12.0, TRACK);
                            let s = Stroke::new(2.0, ACCENT);
                            ui.painter().line_segment([pos2(c.x - 4.2, c.y + 0.3), pos2(c.x - 1.2, c.y + 3.4)], s);
                            ui.painter().line_segment([pos2(c.x - 1.2, c.y + 3.4), pos2(c.x + 4.4, c.y - 3.0)], s);
                        } else if i == self.page {
                            ui.painter().circle_filled(c, 12.0, ACCENT);
                            ui.painter().text(c, Align2::CENTER_CENTER, format!("{}", i + 1), bold(12.5), ON_ACCENT);
                        } else {
                            ui.painter().circle_stroke(c, 11.5, Stroke::new(1.2, Color32::from_rgb(58, 58, 66)));
                            ui.painter().text(c, Align2::CENTER_CENTER, format!("{}", i + 1), FontId::new(12.5, FontFamily::Proportional), FAINT);
                        }
                        if i > 0 {
                            let (r, _) = ui.allocate_exact_size(vec2(26.0, 24.0), Sense::hover());
                            ui.painter().line_segment([pos2(r.left(), r.center().y), pos2(r.right(), r.center().y)], Stroke::new(1.2, LINE));
                        }
                    }
                });
            });
        });
    }

    fn ui_nav(&mut self, ui: &mut Ui, ctx: &egui::Context) {
        let running = self.phase == Phase::Running;
        ui.horizontal_centered(|ui| {
            if self.settings {
                if line_btn(ui, "기본값 채우기", 140.0, 46.0, INK) {
                    self.rule_vals = RULES.iter().map(|r| r.2.to_string()).collect();
                    self.set_msg.clear();
                }
                if !self.set_msg.is_empty() {
                    ui.label(RichText::new(&self.set_msg).size(12.5).color(ERR));
                }
            } else {
            ui.label(RichText::new(format!("v{}", env!("CARGO_PKG_VERSION"))).size(12.0).color(FAINT));
            if ui.add(egui::Label::new(RichText::new("업데이트 확인").size(12.0).color(SUB).underline()).sense(Sense::click())).on_hover_cursor(CursorIcon::PointingHand).clicked() {
                self.check_update_manual(ctx);
            }
            if !self.upd_note.is_empty() {
                ui.label(RichText::new(&self.upd_note).size(12.0).color(SUB));
            }
            }
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.spacing_mut().item_spacing.x = 10.0;
                if self.settings {
                    if solid_btn(ui, "완료", true, 132.0, 46.0, ACCENT) {
                        // 완료 = 저장. 바꾼 게 없고 내 기본틀도 없으면 아무것도 만들지 않는다.
                        if self.rule_vals == read_rules() && !frame_exists() {
                            self.settings = false;
                        } else {
                            match write_rules(&self.rule_vals) {
                                Ok(()) => self.settings = false,
                                Err(e) => self.set_msg = e,
                            }
                        }
                    }
                    return;
                }
                match self.page {
                    0 => {
                        if solid_btn(ui, "다음", self.has_psd(), 132.0, 46.0, ACCENT) {
                            self.page = 1;
                        }
                    }
                    1 => {
                        if solid_btn(ui, "변환 시작", self.has_psd(), 148.0, 46.0, ACCENT) {
                            self.start(ctx);
                        }
                        if line_btn(ui, "이전", 88.0, 46.0, INK) {
                            self.page = 0;
                        }
                    }
                    2 => {
                        if running {
                            if line_btn(ui, "취소", 96.0, 46.0, ERR) {
                                self.cancel();
                            }
                        } else if solid_btn(ui, "옵션으로", true, 132.0, 46.0, ACCENT) {
                            self.page = 1;
                            self.phase = Phase::Idle;
                        }
                    }
                    _ => {
                        if solid_btn(ui, "새로 변환", true, 132.0, 46.0, ACCENT) {
                            self.reset_all();
                        }
                    }
                }
            });
        });
    }

    fn heading(&self, ui: &mut Ui, title: &str, sub: &str) {
        ui.label(RichText::new(title).font(bold(30.0)));
        if !sub.is_empty() {
            ui.label(RichText::new(sub).size(14.5).color(SUB));
        }
    }

    // ================= 1단계: 파일 =================
    fn page_file(&mut self, ui: &mut Ui, ctx: &egui::Context) {
        self.heading(ui, "PSD 파일을 올려주세요", "끌어다 놓거나 클릭해서 고르세요");
        ui.add_space(14.0);
        let w = ui.available_width();
        let (rect, resp) = ui.allocate_exact_size(vec2(w, 270.0), Sense::click());
        let hovering = ctx.input(|i| !i.raw.hovered_files.is_empty());
        let hot = hovering || resp.hovered();
        ui.painter().rect(rect, Rounding::same(26.0), PANEL, Stroke::new(if hot { 2.0 } else { 1.0 }, if hot { ACCENT } else { Color32::from_rgb(58, 58, 66) }));
        let c = rect.center();
        if self.has_psd() && !hovering {
            let p = PathBuf::from(&self.psd);
            let mut name = p.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
            if name.chars().count() > 34 {
                name = name.chars().take(33).collect::<String>() + "…";
            }
            let size = std::fs::metadata(&p).map(|m| m.len() as f64 / 1_048_576.0).unwrap_or(0.0);
            let ic = Rect::from_center_size(pos2(c.x, c.y - 52.0), vec2(60.0, 74.0));
            ui.painter().rect_filled(ic, Rounding::same(16.0), ACCENT);
            ui.painter().text(ic.center(), Align2::CENTER_CENTER, "PSD", bold(15.0), ON_ACCENT);
            ui.painter().text(pos2(c.x, c.y + 18.0), Align2::CENTER_CENTER, name, bold(19.0), INK);
            ui.painter().text(pos2(c.x, c.y + 46.0), Align2::CENTER_CENTER, format!("{:.1} MB", size), FontId::new(14.0, FontFamily::Proportional), SUB);
            ui.painter().text(pos2(c.x, c.y + 82.0), Align2::CENTER_CENTER, "다른 파일 고르기", FontId::new(13.0, FontFamily::Proportional), if hot { ACCENT } else { FAINT });
        } else {
            let ic = pos2(c.x, c.y - 34.0);
            ui.painter().circle_filled(ic, 34.0, ACCENT);
            let s = Stroke::new(2.8, ON_ACCENT);
            ui.painter().line_segment([pos2(ic.x - 11.0, ic.y), pos2(ic.x + 11.0, ic.y)], s);
            ui.painter().line_segment([pos2(ic.x, ic.y - 11.0), pos2(ic.x, ic.y + 11.0)], s);
            let t = if hovering { "여기에 놓으세요" } else { "PSD 파일 선택" };
            ui.painter().text(pos2(c.x, c.y + 28.0), Align2::CENTER_CENTER, t, bold(20.0), INK);
            ui.painter().text(pos2(c.x, c.y + 56.0), Align2::CENTER_CENTER, ".psd · .psb", FontId::new(13.5, FontFamily::Proportional), FAINT);
        }
        if hot {
            ctx.set_cursor_icon(CursorIcon::PointingHand);
        }
        if resp.clicked() {
            self.pick_psd();
        }
    }

    // ================= 2단계: 옵션 =================
    fn opt_row(&self, ui: &mut Ui, title: &str, hint: &str) {
        ui.horizontal(|ui| {
            ui.label(RichText::new(title).font(bold(14.5)));
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.label(RichText::new(hint).size(12.5).color(SUB));
            });
        });
    }

    fn page_options(&mut self, ui: &mut Ui, _ctx: &egui::Context) {
        self.heading(ui, "이렇게 만들까요?", "");
        ui.add_space(8.0);
        // 프리셋: 옵션 묶음을 이름 붙여 저장해 두고 불러온다
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 8.0;
            ui.label(RichText::new("프리셋").size(13.0).color(SUB));
            let mut pick: Option<String> = None;
            egui::ComboBox::from_id_salt("preset_pick").selected_text(if self.presets.is_empty() { "저장된 프리셋 없음" } else { "불러오기" }).width(150.0).show_ui(ui, |ui| {
                for n in &self.presets {
                    if ui.selectable_label(false, n).clicked() {
                        pick = Some(n.clone());
                    }
                }
            });
            if let Some(n) = pick {
                match std::fs::read_to_string(preset_file(&n)).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()) {
                    Some(v) => {
                        self.apply_preset(&v);
                        self.preset_name = n.clone();
                        self.preset_msg = format!("'{n}' 불러옴");
                    }
                    None => self.preset_msg = "프리셋을 읽지 못했어요".into(),
                }
            }
            ui.add_sized([120.0, 28.0], egui::TextEdit::singleline(&mut self.preset_name).hint_text("이름").margin(vec2(8.0, 6.0)));
            if line_btn(ui, "저장", 56.0, 28.0, INK) && !self.preset_name.trim().is_empty() {
                let _ = std::fs::create_dir_all(presets_dir());
                self.preset_msg = match std::fs::write(preset_file(&self.preset_name), serde_json::to_string_pretty(&self.preset_json()).unwrap_or_default()) {
                    Ok(()) => {
                        self.presets = list_presets();
                        format!("'{}' 저장함", self.preset_name.trim())
                    }
                    Err(e) => format!("저장 실패: {e}"),
                };
            }
            if line_btn(ui, "삭제", 56.0, 28.0, INK) && self.presets.iter().any(|n| *n == self.preset_name.trim()) {
                let _ = std::fs::remove_file(preset_file(&self.preset_name));
                self.preset_msg = format!("'{}' 삭제함", self.preset_name.trim());
                self.presets = list_presets();
            }
            if !self.preset_msg.is_empty() {
                ui.label(RichText::new(&self.preset_msg).size(12.0).color(FAINT));
            }
        });
        ui.add_space(8.0);
        egui::Frame::none().fill(PANEL).rounding(22.0).inner_margin(Margin::same(24.0)).stroke(Stroke::new(1.0, LINE)).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.spacing_mut().item_spacing.y = 8.0;
            self.opt_row(ui, "이미지 화질", QUALITIES[self.quality].2);
            let q: Vec<&str> = QUALITIES.iter().map(|x| x.0).collect();
            segmented(ui, "q", &mut self.quality, &q);
            ui.add_space(8.0);
            self.opt_row(ui, "이미지 저장 크기", SCALES[self.img_scale].1);
            let s: Vec<&str> = SCALES.iter().map(|x| x.0).collect();
            segmented(ui, "s", &mut self.img_scale, &s);
            ui.add_space(8.0);
            self.opt_row(ui, "CSS 숫자", CSS_ROUNDS[self.css_round].2);
            let r: Vec<&str> = CSS_ROUNDS.iter().map(|x| x.0).collect();
            segmented(ui, "r", &mut self.css_round, &r);
            ui.add_space(8.0);
            self.opt_row(ui, "자동 보강", "끄면 PSD 구조 그대로");
            ui.horizontal_wrapped(|ui| {
                ui.spacing_mut().item_spacing.x = 18.0;
                ui.checkbox(&mut self.a11y, "접근성·SEO");
                ui.checkbox(&mut self.repeat, "반복 요소(ul/li)");
                ui.checkbox(&mut self.forms, "폼·게시판");
            });
            ui.add_space(8.0);
            self.opt_row(ui, "다른 형식으로도 내보내기", "결과 폴더의 targets 폴더에 만들어요");
            ui.horizontal_wrapped(|ui| {
                ui.spacing_mut().item_spacing.x = 18.0;
                for (i, (_, label)) in TARGETS.iter().enumerate() {
                    ui.checkbox(&mut self.targets[i], *label);
                }
            });
            ui.add_space(8.0);
            self.opt_row(ui, "저장 위치", "");
            ui.horizontal(|ui| {
                let w = ui.available_width() - 84.0;
                ui.add_sized([w, 38.0], egui::TextEdit::singleline(&mut self.out).margin(vec2(12.0, 10.0)));
                if line_btn(ui, "변경", 74.0, 38.0, INK) {
                    if let Some(p) = rfd::FileDialog::new().pick_folder() {
                        self.out = p.to_string_lossy().into_owned();
                    }
                }
            });
        });
        ui.add_space(4.0);
        let arrow = if self.advanced { "−" } else { "+" };
        if ui.add(egui::Label::new(RichText::new(format!("{arrow}  고급")).size(13.0).color(SUB)).sense(Sense::click())).on_hover_cursor(CursorIcon::PointingHand).clicked() {
            self.advanced = !self.advanced;
        }
        if self.advanced {
            ui.checkbox(&mut self.structure, "구조화 변환 (끄면 통이미지 초안)");
            ui.horizontal(|ui| {
                let w = ui.available_width() - 84.0;
                ui.add_sized([w, 38.0], egui::TextEdit::singleline(&mut self.zip).hint_text("소스 ZIP (선택)").margin(vec2(12.0, 10.0)));
                if line_btn(ui, "선택", 74.0, 38.0, INK) {
                    if let Some(p) = rfd::FileDialog::new().add_filter("ZIP", &["zip"]).pick_file() {
                        self.zip = p.to_string_lossy().into_owned();
                    }
                }
            });
        }
    }

    // ================= 설정 =================
    fn page_settings(&mut self, ui: &mut Ui, _ctx: &egui::Context) {
        if self.rule_vals.len() != RULES.len() {
            self.rule_vals = read_rules();
        }
        self.heading(ui, "설정", "회사 기본값을 내 방식으로 바꿀 수 있어요");
        ui.add_space(8.0);
        egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
            ui.set_width(ui.available_width());
            egui::Frame::none().fill(PANEL).rounding(22.0).inner_margin(Margin::same(24.0)).stroke(Stroke::new(1.0, LINE)).show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.spacing_mut().item_spacing.y = 8.0;
                let mine = frame_exists();
                self.opt_row(ui, "기본틀", if mine { "내 기본틀 사용 중" } else { "내장 회사 기본틀 사용 중" });
                ui.label(RichText::new("default.css · layout.css · head.php · top.php · bottom.php · link.php · js 파일을 직접 고치면 다음 변환부터 적용돼요.").size(12.5).color(SUB));
                ui.horizontal(|ui| {
                    ui.spacing_mut().item_spacing.x = 12.0;
                    if solid_btn(ui, if mine { "기본틀 폴더 열기" } else { "기본틀 꺼내서 편집" }, true, 168.0, 38.0, ACCENT) {
                        match export_frame() {
                            Ok(()) => {
                                let _ = Command::new("explorer").arg(frame_dir()).spawn();
                                self.set_msg.clear();
                            }
                            Err(e) => self.set_msg = e,
                        }
                    }
                    if mine {
                        let label = if self.confirm_reset { "정말 되돌릴까요?" } else { "원래대로" };
                        if line_btn(ui, label, 132.0, 38.0, if self.confirm_reset { ERR } else { INK }) {
                            if self.confirm_reset {
                                let _ = std::fs::remove_dir_all(frame_dir());
                                self.rule_vals = read_rules();
                                self.confirm_reset = false;
                                self.set_msg = "내장 회사 기본틀로 되돌렸어요.".into();
                            } else {
                                self.confirm_reset = true;
                            }
                        }
                    }
                });
                ui.add_space(14.0);
                self.opt_row(ui, "변환 규칙", "비우면 기본값");
                egui::Grid::new("rules").num_columns(2).spacing([16.0, 8.0]).show(ui, |ui| {
                    for (i, (_, label, def, _)) in RULES.iter().enumerate() {
                        let def: &&str = def;
                        ui.label(RichText::new(*label).size(13.5).color(SUB));
                        if i < 2 {
                            // 폭: 자동 인식 체크박스 + 숫자
                            let mut auto = self.rule_vals[i].eq_ignore_ascii_case("auto");
                            let manual = if i == 0 { "1400" } else { "1600" };
                            ui.horizontal(|ui| {
                                ui.spacing_mut().item_spacing.x = 12.0;
                                ui.add_enabled_ui(!auto, |ui| {
                                    let shown = if auto { &mut String::new() } else { &mut self.rule_vals[i] };
                                    ui.add_sized([(ui.available_width() - 110.0).max(100.0), 34.0], egui::TextEdit::singleline(shown).hint_text(if auto { "PSD에서 알아냄" } else { manual }).margin(vec2(10.0, 8.0)));
                                });
                                if ui.checkbox(&mut auto, "자동 인식").changed() {
                                    self.rule_vals[i] = if auto { "auto".into() } else { manual.to_string() };
                                }
                            });
                        } else {
                            ui.add_sized([ui.available_width().max(160.0), 34.0], egui::TextEdit::singleline(&mut self.rule_vals[i]).hint_text(*def).margin(vec2(10.0, 8.0)));
                        }
                        ui.end_row();
                    }
                });
            });
        });
    }

    // ================= 3단계: 변환 =================
    fn page_run(&mut self, ui: &mut Ui, _ctx: &egui::Context) {
        let running = self.phase == Phase::Running;
        let failed = self.phase == Phase::Failed;
        let col = if failed { ERR } else { INK };
        let title = if failed { "변환에 실패했어요" } else if running { "변환하는 중" } else { "멈췄어요" };
        self.heading(ui, title, "");
        ui.add_space(6.0);
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 4.0;
            ui.label(RichText::new(format!("{}", (self.shown * 100.0).round() as i32)).font(bold(88.0)).color(col));
            ui.label(RichText::new("%").font(bold(28.0)).color(FAINT));
            ui.with_layout(Layout::right_to_left(Align::BOTTOM), |ui| {
                ui.label(RichText::new(fmt_dur(self.elapsed)).size(14.0).color(SUB));
            });
        });
        let (bar, _) = ui.allocate_exact_size(vec2(ui.available_width(), 8.0), Sense::hover());
        ui.painter().rect_filled(bar, Rounding::same(4.0), TRACK);
        let mut fill = bar;
        fill.set_width((bar.width() * self.shown.clamp(0.0, 1.0)).max(if self.shown > 0.0 { 8.0 } else { 0.0 }));
        ui.painter().rect_filled(fill, Rounding::same(4.0), if failed { ERR } else { ACCENT });
        ui.add_space(10.0);
        let cur = STAGES.iter().position(|s| self.target < s.2).unwrap_or(STAGES.len() - 1);
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 22.0;
            for (i, (name, _, _)) in STAGES.iter().enumerate() {
                let (c, f) = if i < cur { (INK, FontId::new(14.0, FontFamily::Proportional)) } else if i == cur { (if failed { ERR } else { ACCENT }, bold(14.0)) } else { (FAINT, FontId::new(14.0, FontFamily::Proportional)) };
                ui.label(RichText::new(*name).font(f).color(c));
            }
        });
        ui.add_space(6.0);
        let msg = if self.step.is_empty() { "준비하는 중".to_string() } else { self.step.clone() };
        ui.add(egui::Label::new(RichText::new(msg).size(14.0).color(SUB)).truncate());
        ui.add_space(12.0);
        if ui.add(egui::Label::new(RichText::new(if self.show_log || failed { "기록 숨기기" } else { "기록 보기" }).size(13.0).color(SUB).underline()).sense(Sense::click())).on_hover_cursor(CursorIcon::PointingHand).clicked() {
            self.show_log = !self.show_log;
        }
        if self.show_log || failed {
            let term_w = ui.available_width();
            egui::Frame::none().fill(TERM_BG).rounding(14.0).inner_margin(Margin::symmetric(14.0, 10.0)).show(ui, |ui| {
                ui.set_width(term_w - 28.0);
                ui.set_max_width(term_w - 28.0);
                ui.set_clip_rect(ui.max_rect().intersect(ui.clip_rect()));
                ui.set_height((ui.available_height() - 24.0).clamp(80.0, 190.0));
                egui::ScrollArea::vertical().stick_to_bottom(true).auto_shrink([false, false]).show(ui, |ui| {
                    ui.spacing_mut().item_spacing.y = 3.0;
                    let n = self.feed.len();
                    for (i, (time, msg, is_log)) in self.feed.iter().enumerate() {
                        let last = i + 1 == n && running;
                        let c = if *is_log { Color32::from_rgb(130, 130, 134) } else if last { Color32::from_rgb(245, 245, 245) } else { Color32::from_rgb(190, 190, 194) };
                        ui.horizontal(|ui| {
                            ui.spacing_mut().item_spacing.x = 10.0;
                            ui.label(RichText::new(time).font(FontId::new(12.0, FontFamily::Monospace)).color(Color32::from_rgb(95, 95, 100)));
                            ui.add(egui::Label::new(RichText::new(msg.as_str()).font(FontId::new(12.5, FontFamily::Monospace)).color(c)).truncate()).on_hover_text(msg.as_str());
                        });
                    }
                });
            });
        }
    }

    // ================= 4단계: 결과 =================
    fn page_result(&mut self, ui: &mut Ui, _ctx: &egui::Context) {
        let total = ui.available_width();
        let side_w = 290.0;
        let gap = 20.0;
        let left_w = total - side_w - gap;
        let h = ui.available_height();
        ui.horizontal_top(|ui| {
            ui.spacing_mut().item_spacing.x = gap;
            ui.allocate_ui_with_layout(vec2(left_w, h), Layout::top_down(Align::Min), |ui| {
                ui.set_width(left_w);
                ui.spacing_mut().item_spacing.y = 12.0;
                ui.allocate_ui(vec2(250.0, 38.0), |ui| {
                    segmented(ui, "pv", &mut self.pv_tab, &["변환 결과", "PSD 원본"]);
                });
                let tex = if self.pv_tab == 0 { self.tex_page.clone() } else { self.tex_psd.clone() };
                let ph = ui.available_height();
                egui::Frame::none().fill(PANEL).rounding(20.0).stroke(Stroke::new(1.0, LINE)).inner_margin(Margin::same(10.0)).show(ui, |ui| {
                    ui.set_width(left_w - 20.0);
                    ui.set_height((ph - 22.0).max(100.0));
                    match tex {
                        Some(t) => {
                            let w = ui.available_width() - 6.0;
                            let sz = t.size_vec2();
                            let hh = w * sz.y / sz.x;
                            egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
                                ui.add(egui::Image::new((t.id(), vec2(w, hh))).rounding(Rounding::same(10.0)));
                            });
                        }
                        None => {
                            ui.add_space(ph * 0.3);
                            ui.vertical_centered(|ui| {
                                ui.label(RichText::new("미리보기를 만들지 못했어요").font(bold(15.0)));
                                ui.label(RichText::new("오른쪽의 '브라우저에서 보기'로 확인해 주세요").size(13.0).color(SUB));
                            });
                        }
                    }
                });
            });
            ui.allocate_ui_with_layout(vec2(side_w, h), Layout::top_down(Align::Min), |ui| {
                ui.set_width(side_w);
                egui::Frame::none().fill(PANEL).rounding(20.0).stroke(Stroke::new(1.0, LINE)).inner_margin(Margin::same(22.0)).show(ui, |ui| {
                    ui.set_width(side_w - 44.0);
                    ui.spacing_mut().item_spacing.y = 10.0;
                    ui.label(RichText::new("완료").font(bold(13.0)).color(OK));
                    match self.match_pct {
                        Some(m) if m >= 0.0 => {
                            let col = if m >= 95.0 { OK } else if m >= 85.0 { Color32::from_rgb(202, 138, 4) } else { ERR };
                            ui.label(RichText::new(format!("{:.1}%", m)).font(bold(52.0)).color(col));
                            ui.label(RichText::new("PSD와 일치").size(13.5).color(SUB));
                        }
                        _ => {
                            ui.label(RichText::new("일치율 측정 불가").font(bold(18.0)));
                            ui.label(RichText::new("Edge 또는 Chrome 필요").size(13.0).color(SUB));
                        }
                    }
                    ui.add_space(6.0);
                    let bw = ui.available_width();
                    if let Some(o) = self.last_out.clone() {
                        if solid_btn(ui, "결과 폴더 열기", true, bw, 46.0, ACCENT) {
                            let _ = Command::new("explorer").arg(&o).spawn();
                        }
                        if line_btn(ui, "브라우저에서 보기", bw, 46.0, INK) {
                            let _ = Command::new("cmd").args(["/C", "start", ""]).arg(o.join("preview.html")).creation_flags(CREATE_NO_WINDOW).spawn();
                        }
                        if self.mismatch_n > 0 && line_btn(ui, &format!("불일치 보고서 · {}곳", self.mismatch_n), bw, 46.0, INK) {
                            let _ = Command::new("cmd").args(["/C", "start", ""]).arg(o.join("analysis").join("mismatch-report.html")).creation_flags(CREATE_NO_WINDOW).spawn();
                        }
                    }
                    if let Some(z) = self.zip_out.clone() {
                        if line_btn(ui, "ZIP 위치", ui.available_width(), 46.0, INK) {
                            let _ = Command::new("explorer").arg(format!("/select,{}", z.display())).spawn();
                        }
                    }
                });
            });
        });
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        if self.phase == Phase::Running {
            if let Some(t) = self.started {
                self.elapsed = t.elapsed();
            }
        }
        while let Ok(m) = self.rx.try_recv() {
            match m {
                Msg::Progress(p, s) => {
                    if p >= 0.0 {
                        self.target = self.target.max(p.min(1.0));
                    }
                    if !s.is_empty() {
                        self.step = s.clone();
                        self.push_feed(&s, false);
                    }
                }
                Msg::Log(s) => {
                    if let Some(z) = s.strip_prefix("ZIP: ") {
                        self.zip_out = Some(PathBuf::from(z.trim()));
                    }
                    let line = s.trim_end().to_string();
                    if !line.is_empty() {
                        self.push_feed(&line, true);
                    }
                }
                Msg::Match(v) => {
                    self.match_pct = Some(v);
                    if v >= 0.0 {
                        self.push_feed(&format!("PSD 일치율 {:.1}%", v), false);
                    }
                }
                Msg::Mismatch(n) => {
                    self.mismatch_n = n;
                }
                Msg::UpdateFound(info) => {
                    self.update = Some(info);
                    self.upd_note.clear();
                }
                Msg::UpdateNote(t) => self.upd_note = t,
                Msg::UpdateProgress(p) => self.upd_progress = p,
                Msg::UpdateFailed(e) => {
                    self.upd_state = 2;
                    self.upd_msg = e;
                }
                Msg::UpdateReady(path) => {
                    if std::env::var("PSDPUB_UPDATE_DRYRUN").is_ok() {
                        self.upd_state = 2;
                        self.upd_msg = format!("(시험) 내려받기·체크섬 검증 성공: {}", path.display());
                    } else {
                        // 조용히 설치(업그레이드)하고, 설치가 끝나면 설치 프로그램이 앱을 다시 실행한다
                        let _ = Command::new(&path).args(["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]).spawn();
                        std::process::exit(0);
                    }
                }
                Msg::Done(ok, out) => {
                    if let Some(t) = self.started {
                        self.elapsed = t.elapsed();
                    }
                    if self.cancelled {
                        self.phase = Phase::Cancelled;
                        self.step = "사용자가 취소했습니다.".into();
                        self.page = 1;
                        self.push_feed("취소했습니다", false);
                    } else if ok {
                        self.phase = Phase::Done;
                        self.target = 1.0;
                        self.step = "모든 파일이 만들어졌습니다.".into();
                        self.push_feed("완료 — 모든 파일이 만들어졌습니다", false);
                        self.last_out = Some(out);
                        self.page = 3;
                        self.pv_tab = 0;
                        self.load_previews(ctx);
                    } else {
                        self.phase = Phase::Failed;
                        self.step = "오류가 발생했습니다.".into();
                    }
                }
            }
        }
        let diff = self.target - self.shown;
        if diff.abs() > 0.001 {
            self.shown += diff * 0.14;
            ctx.request_repaint();
        } else {
            self.shown = self.target;
        }
        if self.phase == Phase::Running {
            ctx.request_repaint_after(Duration::from_millis(33));
        }
        if self.update.is_some() && self.upd_state == 0 && std::env::var("PSDPUB_UPDATE_AUTO").is_ok() {
            self.start_update(ctx); // 시험용: 새 버전을 찾으면 바로 내려받기
        }
        if self.autostart && !self.psd.is_empty() {
            self.autostart = false;
            self.start(ctx);
        }
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if self.phase != Phase::Running {
            if let Some(p) = dropped.iter().filter_map(|f| f.path.clone()).next() {
                let ext = p.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
                if ext == "psd" || ext == "psb" {
                    self.psd = p.to_string_lossy().into_owned();
                    if self.page >= 2 {
                        self.page = 1;
                    }
                    self.phase = Phase::Idle;
                    self.feed.clear();
                    self.target = 0.0;
                    self.shown = 0.0;
                }
            }
        }

        egui::TopBottomPanel::top("hdr").exact_height(72.0).frame(egui::Frame::none().fill(BG).inner_margin(Margin::symmetric(32.0, 12.0))).show(ctx, |ui| self.ui_header(ui));
        egui::TopBottomPanel::bottom("nav").exact_height(78.0).frame(egui::Frame::none().fill(BG).inner_margin(Margin::symmetric(32.0, 16.0))).show(ctx, |ui| self.ui_nav(ui, ctx));
        egui::CentralPanel::default().frame(egui::Frame::none().fill(BG).inner_margin(Margin::symmetric(32.0, 8.0))).show(ctx, |ui| {
            ui.set_clip_rect(ui.max_rect());
            if self.update.is_some() {
                self.ui_update_banner(ui, ctx);
                ui.add_space(6.0);
            }
            if self.page == 3 && !self.settings {
                self.page_result(ui, ctx);
            } else {
                let avail = ui.available_width();
                let cw = avail.min(620.0);
                let pad = (avail - cw) / 2.0;
                ui.horizontal_top(|ui| {
                    ui.spacing_mut().item_spacing.x = 0.0;
                    ui.add_space(pad);
                    ui.vertical(|ui| {
                        ui.set_width(cw);
                        ui.spacing_mut().item_spacing.y = 8.0;
                        ui.add_space(10.0);
                        match self.page {
                            _ if self.settings => self.page_settings(ui, ctx),
                            0 => self.page_file(ui, ctx),
                            1 => self.page_options(ui, ctx),
                            _ => self.page_run(ui, ctx),
                        }
                    });
                });
            }
        });
    }
}

fn main() -> eframe::Result<()> {
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_icon(egui::IconData { rgba: include_bytes!("../../assets/app-64.rgba").to_vec(), width: 64, height: 64 })
            .with_inner_size([1000.0, 740.0])
            .with_min_inner_size([860.0, 660.0])
            .with_drag_and_drop(true),
        ..Default::default()
    };
    eframe::run_native(&format!("Pengo {}", env!("CARGO_PKG_VERSION")), opts, Box::new(|cc| Ok(Box::new(App::new(cc)))))
}
