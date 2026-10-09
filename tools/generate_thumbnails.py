# -*- coding: utf-8 -*-
"""为现有邀请函模板补生成 thumbnail.jpg；幂等，可重复运行。"""
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from server import _generate_thumbnail  # noqa: E402

base = ROOT / "assets" / "templates"
for d in sorted(base.glob("t*")):
    if (d / "config.json").exists() and (d / "background.png").exists():
        _generate_thumbnail(d)
        p = d / "thumbnail.jpg"
        print(d.name, p.stat().st_size, "bytes")
