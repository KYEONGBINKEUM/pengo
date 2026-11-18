// 실행 파일(exe)에 아이콘과 제품 정보를 넣는다. 실패해도 빌드는 계속한다(아이콘만 빠짐).
fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").map(|v| v == "windows").unwrap_or(false) {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../assets/app.ico");
        res.set("ProductName", "Pengo");
        res.set("FileDescription", "Pengo");
        res.set("CompanyName", "Pengo");
        if let Err(e) = res.compile() {
            println!("cargo:warning=아이콘을 exe에 넣지 못했습니다: {e}");
        }
    }
}
