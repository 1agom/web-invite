# -*- coding: utf-8 -*-
"""打包云端静态站点：本机模板 → dist-site/（纯前端版，hsk-cli file-hosting 发布用）
包含：index.html + templates.json + assets/<id>/background.png + fonts/
不含：reference.png（校准用图，访客不需要，减半体积）、source.psd、服务端文件
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
TPL = ROOT / "assets" / "templates"
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "dist-site"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    (OUT / "fonts").mkdir()
    (OUT / "vendor").mkdir()
    shutil.copy2(ROOT / "index.html", OUT / "index.html")
    for vendor_file in ("xlsx.full.min.js", "XLSX-LICENSE.txt"):
        src = ROOT / "vendor" / vendor_file
        if src.exists():
            shutil.copy2(src, OUT / "vendor" / vendor_file)

    site = []
    fonts_used = set()
    for d in sorted(TPL.iterdir()):
        cfgp = d / "config.json"
        if not cfgp.exists():
            continue
        tid = d.name
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        bg = d / "background.png"
        if not bg.exists():
            print("跳过（缺 background.png）:", tid, cfg.get("title"))
            continue
        (OUT / "assets" / tid).mkdir(parents=True, exist_ok=True)
        shutil.copy2(bg, OUT / "assets" / tid / "background.png")
        thumb = d / "thumbnail.jpg"
        if not thumb.exists():
            ref = d / "reference.png"
            if ref.exists():
                from PIL import Image
                with Image.open(ref) as im:
                    im = im.convert("RGB")
                    im.thumbnail((360, 640), Image.Resampling.LANCZOS)
                    im.save(thumb, "JPEG", quality=78, optimize=True, progressive=True)
        if thumb.exists():
            shutil.copy2(thumb, OUT / "assets" / tid / "thumbnail.jpg")
        for f in cfg.get("fonts", []):
            if f.get("file"):
                fonts_used.add(f["file"])
        site.append({"id": tid, "name": cfg.get("title") or tid, "config": cfg})

    missing = []
    for fn in sorted(fonts_used):
        src = FONTS / fn
        if src.exists():
            shutil.copy2(src, OUT / "fonts" / fn)
        else:
            missing.append(fn)

    (OUT / "templates.json").write_text(
        json.dumps(site, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"打包完成 dist-site\\：{len(site)} 个模板，{n} 个文件，共 {size / 1048576:.1f} MB")
    if missing:
        print("⚠ 字体缺失：", "、".join(missing))
    print("已包含缩略图：", sum(1 for f in OUT.rglob("thumbnail.jpg")), "张")
    print("发布：hsk-cli file-hosting dist-site --entry-file index.html --format json")


if __name__ == "__main__":
    main()
