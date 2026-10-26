#!/usr/bin/env python3
"""
RustDesk kaynak agacini sirket markasina gore yamalar (Windows oncelikli).

Fork'ta kaynak dosyalar commit'lenmez; bu script CI'da derlemeden hemen once
calistirilir. Boylece upstream merge'lerinde cakisma olmaz. Upstream'de bir
desen degisirse script hata verir (sessizce eksik rebrand yapmaz).

Ornek:
  python rebrand.py --repo ../rustdesk --app-name AcmeDesk --company "Acme A.S." \
      --server 78.186.250.188 --key mzidVnwnVO8qMyQQIvOi8Rg2ayFxd4cenlmhRRCRRzk= \
      --icon branding/icon.png --logo branding/logo.png

Sunucu ve key parametre verilmezse RENDEZVOUS_SERVER / RS_PUB_KEY ortam
degiskenlerinden okunur (GitHub Actions secret'lari icin).

--check: dosyalari degistirmeden tum desenlerin bulundugunu dogrular
(upstream merge sonrasi kullanin).
"""
import argparse
import base64
import datetime
import os
import re
import sys
from pathlib import Path


class Patcher:
    def __init__(self, repo: Path, check_only: bool):
        self.repo = repo
        self.check_only = check_only
        self.errors = []
        self.changed = []

    def sub(self, rel, pattern, repl, count_expected=None, flags=re.M):
        """Regex ile degistir. Desen bulunamazsa hata biriktir."""
        path = self.repo / rel
        if not path.is_file():
            self.errors.append(f"{rel}: dosya yok")
            return
        with open(path, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        new, n = re.subn(pattern, repl, text, flags=flags)
        if n == 0 or (count_expected is not None and n != count_expected):
            self.errors.append(
                f"{rel}: desen {n} kez bulundu (beklenen {count_expected or '>=1'}): {pattern}"
            )
            return
        if not self.check_only and new != text:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            self.changed.append(rel)


def rust_str(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def validate(args):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,31}", args.app_name):
        sys.exit(
            "HATA: --app-name bosluk/ozel karakter icermemeli (servis adi, kurulum "
            "klasoru ve exe adi olarak kullanilir). Ornek: AcmeDesk"
        )
    if args.app_name.lower() == "rustdesk":
        sys.exit("HATA: --app-name RustDesk olamaz.")
    if not args.server or re.search(r"[\s/]|://", args.server):
        sys.exit("HATA: --server (veya RENDEZVOUS_SERVER) 'host' ya da 'host:port' olmali.")
    try:
        if len(base64.b64decode(args.key, validate=True)) != 32:
            raise ValueError
    except Exception:
        sys.exit("HATA: --key (veya RS_PUB_KEY) gecerli bir ed25519 public key (base64, 32 bayt) degil.")


def make_icons(repo: Path, icon_png: Path, check_only: bool):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("HATA: ikon uretimi icin Pillow gerekli: pip install pillow")
    src = Image.open(icon_png).convert("RGBA")
    if src.width != src.height:
        sys.exit(f"HATA: ikon kare olmali, verilen {src.width}x{src.height}")
    if src.width < 256:
        sys.exit("HATA: ikon en az 256x256 olmali (1024x1024 onerilir)")
    if src.width < 1024:
        print(f"UYARI: ikon {src.width}px; 1024x1024 onerilir.")

    def png(rel, size):
        if check_only:
            return
        out = repo / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        src.resize((size, size), Image.LANCZOS).save(out, "PNG")

    def ico(rel, sizes):
        if check_only:
            return
        big = src.resize((256, 256), Image.LANCZOS)
        big.save(repo / rel, format="ICO", sizes=[(s, s) for s in sizes])

    ico("res/icon.ico", [16, 24, 32, 48, 64, 128, 256])       # exe/dll/kurulum ikonu
    ico("flutter/windows/runner/resources/app_icon.ico", [16, 24, 32, 48, 64, 128, 256])
    ico("res/tray-icon.ico", [32])                             # sistem tepsisi (include_bytes)
    png("res/icon.png", 1024)
    png("res/mac-icon.png", 1024)
    png("res/32x32.png", 32)
    png("res/64x64.png", 64)
    png("res/128x128.png", 128)
    png("res/128x128@2x.png", 256)
    png("flutter/assets/icon.png", 256)  # uygulama ici ikon (varsa icon.svg yerine kullanilir)


def make_logo(repo: Path, logo_png: Path, check_only: bool):
    from PIL import Image
    im = Image.open(logo_png).convert("RGBA")
    im.thumbnail((600, 120), Image.LANCZOS)  # uygulama 300x60'a sigdirir; 2x cozunurluk
    if not check_only:
        im.save(repo / "flutter/assets/logo.png", "PNG")


def make_android_icons(repo: Path, icon_png: Path, check_only: bool):
    """Android baslatici ikonlarini (legacy + round + adaptive foreground) uretir.
    Arka plan rengi (ic_launcher_background) zaten beyaz oldugu icin dokunulmaz."""
    if check_only:
        return
    from PIL import Image, ImageDraw
    src = Image.open(icon_png).convert("RGBA")
    base = repo / "flutter/android/app/src/main/res"
    # Legacy kare + yuvarlak ikon (API < 26 ve roundIcon icin)
    legacy = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for d, sz in legacy.items():
        out = src.resize((sz, sz), Image.LANCZOS)
        out.save(base / f"mipmap-{d}/ic_launcher.png", "PNG")
        mask = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, sz - 1, sz - 1), fill=255)
        rnd = out.copy()
        rnd.putalpha(mask)
        rnd.save(base / f"mipmap-{d}/ic_launcher_round.png", "PNG")
    # Adaptive icon foreground: amblem ~%62 guvenli alanda ortalanir, cevresi seffaf.
    fg = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
    for d, sz in fg.items():
        canvas = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        inner = int(sz * 0.62)
        mark = src.resize((inner, inner), Image.LANCZOS)
        off = (sz - inner) // 2
        canvas.paste(mark, (off, off), mark)
        canvas.save(base / f"mipmap-{d}/ic_launcher_foreground.png", "PNG")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="RustDesk kaynak klasoru (varsayilan: .)")
    ap.add_argument("--app-name", required=True, help="Uygulama adi, bosluksuz (orn. AcmeDesk)")
    ap.add_argument("--display-name", help="Dosya ozelliklerindeki aciklama (varsayilan: '<app-name> Remote Desktop')")
    ap.add_argument("--company", required=True, help="Sirket adi (dosya ozellikleri)")
    ap.add_argument("--server", default=os.environ.get("RENDEZVOUS_SERVER", ""), help="ID sunucusu host[:port]")
    ap.add_argument("--key", default=os.environ.get("RS_PUB_KEY", ""), help="Sunucu public key (id_ed25519.pub)")
    ap.add_argument("--icon", type=Path, help="Kare PNG ikon (1024x1024 onerilir)")
    ap.add_argument("--logo", type=Path, help="Ana ekranda gosterilecek yatay logo PNG (istege bagli)")
    ap.add_argument("--website", help="Hakkinda sayfasindaki 'Website' baglantisi")
    ap.add_argument("--privacy-url", help="'Privacy Statement' baglantisi")
    ap.add_argument("--check", action="store_true", help="Degistirmeden sadece desenleri dogrula")
    args = ap.parse_args()
    if args.check:
        args.server = args.server or "example.com"
        args.key = args.key or base64.b64encode(bytes(32)).decode()
    validate(args)

    repo = Path(args.repo).resolve()
    app = args.app_name
    display = args.display_name or f"{app} Remote Desktop"
    year = datetime.date.today().year
    copyright_ = f"Copyright (C) {year} {args.company.rstrip('.')}. Based on RustDesk (C) Purslane Ltd, AGPL-3.0."
    p = Patcher(repo, args.check)

    # 1) Uygulama adi, gomulu sunucu ve key (hbb_common alt modulu)
    cfg = "libs/hbb_common/src/config.rs"
    p.sub(cfg, r'(pub static ref APP_NAME: RwLock<String> = RwLock::new\(")[^"]*(")',
          rf"\g<1>{rust_str(app)}\g<2>", 1)
    p.sub(cfg, r'^pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[[^\]]*\];',
          f'pub const RENDEZVOUS_SERVERS: &[&str] = &["{rust_str(args.server)}"];', 1)
    p.sub(cfg, r'^pub const RS_PUB_KEY: &str = "[^"]*";',
          f'pub const RS_PUB_KEY: &str = "{rust_str(args.key)}";', 1)

    # 2) Windows dosya ozellikleri (Rust ciktisi ve kurulum paketleyici)
    for toml in ("Cargo.toml", "libs/portable/Cargo.toml"):
        p.sub(toml, r'^ProductName = "[^"]*"', f'ProductName = "{app}"', 1)
        p.sub(toml, r'^FileDescription = "[^"]*"', f'FileDescription = "{display}"', 1)
        p.sub(toml, r'^LegalCopyright = "[^"]*"', f'LegalCopyright = "{copyright_}"', 1)
        p.sub(toml, r'^description = "[^"]*"', f'description = "{display}"', 1)
    p.sub("Cargo.toml", r'^OriginalFilename = "[^"]*"', f'OriginalFilename = "{app}.exe"', 1)
    p.sub("libs/portable/Cargo.toml", r'^OriginalFilename = "[^"]*"', f'OriginalFilename = "{app}-setup.exe"', 1)

    # 3) Flutter Windows runner (asil calisan exe'nin ozellikleri ve varsayilan pencere adi)
    rc = "flutter/windows/runner/Runner.rc"
    for field, value in (("CompanyName", args.company), ("FileDescription", display),
                         ("InternalName", app.lower()), ("LegalCopyright", copyright_),
                         ("OriginalFilename", f"{app}.exe"), ("ProductName", app)):
        p.sub(rc, rf'(VALUE "{field}", )"[^"]*"', rf'\g<1>"{value}"', 1)
    p.sub("flutter/windows/runner/main.cpp", r'(std::wstring app_name = L)"[^"]*"', rf'\g<1>"{app}"', 1)

    # 4) Flutter arayuzunde sabit yazilmis ad (ceviriler "RustDesk"i zaten APP_NAME ile degistirir)
    p.sub("flutter/lib/desktop/widgets/tabbar_widget.dart",
          r'(offstage: !showTitle,\s*child: const Text\(\s*)"[^"]*"', rf'\g<1>"{app}"', 1)

    # 4b) Android: baslatici/servis adi (manifest) ve uygulama adi + erisim aciklamasi (strings)
    manifest = "flutter/android/app/src/main/AndroidManifest.xml"
    p.sub(manifest, r'(android:label=)"RustDesk"', rf'\g<1>"{app}"', 1)
    p.sub(manifest, r'(android:label=)"RustDesk Input"', rf'\g<1>"{app} Input"', 1)
    strings = "flutter/android/app/src/main/res/values/strings.xml"
    p.sub(strings, r'(<string name="app_name">)RustDesk(</string>)', rf'\g<1>{app}\g<2>', 1)
    p.sub(strings,
          r'(<string name="accessibility_service_description">[^<]*?)RustDesk([^<]*</string>)',
          rf'\g<1>{app}\g<2>', 1)

    # 5) Istege bagli baglantilar
    if args.privacy_url:
        for f in ("flutter/lib/desktop/pages/desktop_setting_page.dart",
                  "flutter/lib/desktop/pages/install_page.dart"):
            p.sub(f, r"'https://rustdesk\.com/privacy\.html'", f"'{args.privacy_url}'")
    if args.website:
        p.sub("flutter/lib/desktop/pages/desktop_setting_page.dart",
              r"launchUrlString\('https://rustdesk\.com'\)", f"launchUrlString('{args.website}')", 1)

    # 6) Ikon ve logo
    if args.icon:
        make_icons(repo, args.icon, args.check)
        p.changed.append("res/*.ico, res/*.png, flutter/windows/runner/resources/app_icon.ico, flutter/assets/icon.png")
        make_android_icons(repo, args.icon, args.check)
        p.changed.append("flutter/android/app/src/main/res/mipmap-*/ic_launcher*.png")
    if args.logo:
        make_logo(repo, args.logo, args.check)
        p.changed.append("flutter/assets/logo.png")

    if p.errors:
        print("HATA: bazi desenler bulunamadi (upstream degismis olabilir):", file=sys.stderr)
        for e in p.errors:
            print("  - " + e, file=sys.stderr)
        sys.exit(1)
    if args.check:
        print("Tum desenler bulundu, rebrand uygulanabilir.")
    else:
        print(f"Rebrand uygulandi: {app} / sunucu {args.server}")
        for c in sorted(set(p.changed)):
            print("  * " + c)


if __name__ == "__main__":
    main()
