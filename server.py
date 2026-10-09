# -*- coding: utf-8 -*-
"""邀请函生成器 - 本地服务 v2
纯浏览器 Canvas 出图；本服务负责：托管页面/资产、模板管理（PSD 上传/解析/合成背景板）、
字体上传、导出 PNG 落盘。
启动：python server.py        （自动打开浏览器）
      python server.py --no-open
"""
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

if sys.stdout is None:  # No-console Python launchers write diagnostics to the ignored local logs directory.
    _local_log = Path(__file__).parent / "logs" / "pythonw.log"
    _local_log.parent.mkdir(exist_ok=True)
    _logf = _local_log.open("a", encoding="utf-8")
    sys.stdout = _logf
    sys.stderr = _logf

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
LOGS_DIR = ROOT / "logs"
LOG_PATH = LOGS_DIR / "export_log.jsonl"
TEMPLATES_DIR = ASSETS / "templates"
FONTS_DIR = ASSETS / "fonts"
TEMPLATES_INDEX = ASSETS / "templates.json"

for d in (ASSETS, FONTS_DIR, TEMPLATES_DIR, OUTPUT, LOGS_DIR):
    d.mkdir(exist_ok=True)

PORT = int(os.environ.get("INVITE_PORT", "8790"))
# 公开部署：--host 0.0.0.0 或环境变量 INVITE_HOST；设 INVITE_ADMIN_KEY 后，
# 上传/删除模板、改配置、传字体、看统计都需要钥匙，访客只能用模板和导出。
HOST = os.environ.get("INVITE_HOST", "127.0.0.1")
if "--host" in sys.argv:
    HOST = sys.argv[sys.argv.index("--host") + 1]
ADMIN_KEY = os.environ.get("INVITE_ADMIN_KEY", "").strip()
PAGE_PASSWORD = os.environ.get("INVITE_PAGE_PASSWORD", "").strip()
if not ADMIN_KEY or not PAGE_PASSWORD:
    raise RuntimeError("Set INVITE_ADMIN_KEY and INVITE_PAGE_PASSWORD in the environment before starting the server.")

app = FastAPI(title="邀请函生成器")


class ExportItem(BaseModel):
    filename: str
    dataUrl: str


class ExportReq(BaseModel):
    items: list[ExportItem]
    visitor: str = ""
    template: str = ""


class PasswordReq(BaseModel):
    password: str


class BackupReq(BaseModel):
    names: list[str] = []


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]', "_", name).strip().strip(".")
    return name or "邀请函"


# ---------------------------------------------------------------- 管理钥匙 + 访问日志


def _check_admin(request: Request) -> None:
    """设置了 INVITE_ADMIN_KEY 时，写操作与统计接口需要钥匙；未设置=本机开放模式。"""
    if not ADMIN_KEY:
        return
    key = (
        request.headers.get("x-admin-key")
        or request.query_params.get("key")
        or ""
    )
    if key != ADMIN_KEY:
        raise HTTPException(401, "需要管理钥匙")


def _check_page_password(request: Request) -> None:
    if request.headers.get("x-page-password", "") != PAGE_PASSWORD:
        raise HTTPException(401, "需要页面密码")


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return xff or (request.client.host if request.client else "")


def _log_event(request: Request, event: str, **data):
    """访问日志（JSONL，追加写）：谁在什么时间用哪个模板导出了什么。仅管理页可见。"""
    rec = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "ip": _client_ip(request),
        "ua": (request.headers.get("user-agent") or "")[:120],
    }
    rec.update(data)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_log_rows() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


# ---------------------------------------------------------------- PSD 解析

# 占位文字 → 字段规则（按顺序匹配，命中即停）
PLACEHOLDER_RULES = [
    ("测试姓名", "name", "姓名"),
    ("姓名", "name", "姓名"),
    ("名字", "name", "姓名"),
    ("name", "name", "姓名"),
    ("测试职务", "title", "称谓"),
    ("职务", "title", "称谓"),
    ("称谓", "title", "称谓"),
    ("头衔", "title", "称谓"),
    ("title", "title", "称谓"),
    ("测试日期", "date", "日期"),
    ("日期", "date", "日期"),
]

# 下划线空位（连续 3 个及以上下划线族字符）→ 填空字段
BLANK_RE = re.compile(r"[＿_﹍﹎﹉]{3,}")

FIELD_LABELS = {"name": "姓名", "title": "称谓", "date": "日期"}

# 点选字段规则：图层文字（归一化后）精确命中即归入同组，页面上点选切换
# 典型用法：PSD 里放「女士」「先生」两个文字图层（可以隐藏其中一个）
# group 相同的规则 = 互斥抬头：同张 PSD 里多组同时命中时合并为一个点选字段（只渲染选中的一个）
CHOICE_RULES = [
    {
        "id": "honorific", "label": "女士/先生", "group": "heading",
        "options": [
            {"text": "女士", "match": {"女士", "测试女士", "miss", "ms", "mrs"}},
            {"text": "先生", "match": {"先生", "测试先生", "mr"}},
        ],
    },
    {
        "id": "subject", "label": "团队/创作人", "group": "heading",
        "options": [
            {"text": "团队", "match": {"团队", "创作团队", "测试团队"}},
            {"text": "创作人", "match": {"创作人", "测试创作人"}},
        ],
    },
]

GROUP_LABELS = {"heading": "抬头"}


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _clean_font_name(s: str) -> str:
    s = re.sub(r"^[A-Z]{6}\+", "", s or "")  # 去子集前缀 ABCDEF+
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s.lower())


def _hex_color(values) -> str:
    try:
        vals = [float(v) for v in values]
        # 引擎数据实测顺序为 [A, R, G, B]（首位≈1.0，其余为 0-1 的 RGB）
        rgb = vals[1:4] if len(vals) >= 4 else vals[:3]
        r, g, b = [max(0, min(255, round(v * 255))) for v in rgb]
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#000000"


def _get_dpi(psd) -> float:
    """PSD 文档分辨率（DPI），决定 pt→px 换算；取不到按 72。"""
    try:
        for r in psd._record.image_resources:
            if int(getattr(r, "key", 0) or 0) == 1005:  # RESOLUTION_INFO
                d = r.data
                hr = getattr(d, "h_res", None)
                for cand in (hr, getattr(hr, "value", None)):
                    try:
                        v = float(cand)
                        if 1 < v < 10000:
                            return v
                    except (TypeError, ValueError):
                        continue
    except Exception:
        pass
    return 72.0


def _dget(d, key, default=None):
    """engine_data 容器容错取值（Property 不支持 .get）"""
    try:
        v = d[key]
        return default if v is None else v
    except Exception:
        return default


def _run_arrays(ed, key):
    """engine_dict 里 StyleRun/ParagraphRun 的 RunArray 列表"""
    try:
        arr = ed[key]["RunArray"]
        return [arr[i] for i in range(len(arr))]
    except Exception:
        return []


def _style_data(run):
    """从 RunArray 项取样式数据（psd-tools 键名为 StyleSheetData）"""
    ss = _dget(run, "StyleSheet")
    if ss is not None:
        sd = _dget(ss, "StyleSheetData")
        if sd is not None:
            return sd
    return _dget(run, "StyleSheetData", {})


def _para_style_data(run):
    """段落属性：ParagraphRun 项 → ParagraphSheet → Properties（含 Justification）"""
    ps = _dget(run, "ParagraphSheet")
    if ps is not None:
        props = _dget(ps, "Properties")
        if props is not None:
            return props
        sd = _dget(_dget(ps, "StyleSheet"), "StyleSheetData")
        if sd is not None:
            return sd
    return _style_data(run)


_ALIGN_MAP = {"left": "left", "rght": "right", "right": "right",
              "cntr": "center", "cent": "center", "center": "center"}


def _style_extras(layer):
    """取段落对齐与字距（tracking，千分之一 em）"""
    align, tracking = None, 0.0
    try:
        ed = layer.engine_dict
        runs = _run_arrays(ed, "ParagraphRun")
        if runs:
            sd = _para_style_data(runs[0])
            j = _dget(sd, "Justification")
            try:  # Justification 枚举：0=左 1=右 2=居中（3+ 两端对齐按居中处理）
                align = {0: "left", 1: "right", 2: "center", 3: "center", 4: "center"}[int(j)]
            except (TypeError, ValueError, KeyError):
                a = str(_dget(sd, "Alignment", "")).lower()
                for kw, v in _ALIGN_MAP.items():
                    if kw in a:
                        align = v
                        break
        sruns = _run_arrays(ed, "StyleRun")
        if sruns:
            sd = _style_data(sruns[0])
            tracking = float(_dget(sd, "Tracking", 0) or 0)
    except Exception:
        pass
    return align, tracking


def _style_basic(layer):
    """返回 (font_ps, pt_size, hex_color)"""
    font_ps, pt_size, color = "", 0.0, "#000000"
    try:
        fontset = _dget(layer.resource_dict, "FontSet", [])
        sruns = _run_arrays(layer.engine_dict, "StyleRun")
        if sruns:
            sd = _style_data(sruns[0])
            try:
                idx = int(_dget(sd, "Font"))
                if 0 <= idx < len(fontset):
                    font_ps = str(_dget(fontset[idx], "Name", "")).strip("'\"")
            except (TypeError, ValueError):
                pass
            try:
                pt_size = float(_dget(sd, "FontSize", 0) or 0)
            except (TypeError, ValueError):
                pt_size = 0.0
            fill = _dget(sd, "FillColor")
            if fill is not None:
                color = _hex_color(_dget(fill, "Values", []))
    except Exception:
        pass
    return font_ps, pt_size, color


def _analyze_psd(path: Path):
    """解析 PSD：返回 (layers 文字图层信息, psd 对象, warnings)"""
    from psd_tools import PSDImage

    psd = PSDImage.open(str(path))
    dpi = _get_dpi(psd)
    k = dpi / 72.0
    warnings = []
    layers = []
    for layer in psd.descendants():
        if getattr(layer, "kind", None) != "type":
            continue
        text = (layer.text or "").replace("\r", "\n").replace("\v", "\n").strip()
        if not text:
            continue
        font_ps, pt_size, color = _style_basic(layer)
        # 变换矩阵可能整体缩放文字
        scale = 1.0
        try:
            tf = layer.transform
            if tf and tf[0]:
                scale = abs(float(tf[0]))
        except Exception:
            pass
        px_size = pt_size * k * scale if pt_size else 0.0
        if not px_size:  # 兜底：用包围盒高度估
            bbox = layer.bbox
            if bbox and bbox[3] > bbox[1]:
                px_size = (bbox[3] - bbox[1]) * 0.72
        align, tracking = _style_extras(layer)
        layers.append({
            "layerName": layer.name,
            "text": text,
            "fontPS": font_ps,
            "fontSize": round(px_size, 1),
            "color": color,
            "bbox": [int(v) for v in layer.bbox] if layer.bbox else None,
            "align": align,
            "tracking": tracking,
            "visible": bool(getattr(layer, "visible", True)),
        })
    if not layers:
        warnings.append("PSD 中未找到任何文字图层（可能已栅格化或为智能对象）")
    return psd, layers, warnings


def _match_layers(layers):
    """按占位词规则给图层标记 variable 字段；可见图层优先，返回 {fieldId: layer}"""
    matched = {}
    for prefer_visible in (True, False):
        for L in layers:
            if bool(L.get("visible", True)) != prefer_visible:
                continue
            t = _norm_text(L["text"])
            for kw, fid, _label in PLACEHOLDER_RULES:
                if kw in t and fid not in matched:
                    matched[fid] = L
                    L["matched"] = fid
                    break
    return matched


def _choice_fields(layers):
    """识别点选字段；同 group 的多条规则同时命中时合并为一个字段（互斥抬头）"""
    rule_hits = []
    for rule in CHOICE_RULES:
        opt_layers = {}
        for L in layers:
            if L.get("matched"):
                continue
            t = _norm_text(L["text"])
            for opt in rule["options"]:
                if t in opt["match"]:
                    opt_layers[opt["text"]] = L
                    L["matched"] = "choice"
                    break
        if not opt_layers:
            continue
        options = []
        for opt in rule["options"]:
            L = opt_layers.get(opt["text"])
            if L is None:
                continue
            o = _field_from_layer("tmp", opt["text"], L, False)
            options.append({
                "text": opt["text"],
                "x": o["x"], "y": o["y"], "fontSize": o["fontSize"],
                "color": o["color"], "align": o["align"], "baseline": o["baseline"],
                "letterSpacing": o["letterSpacing"], "layerName": L["layerName"],
            })
        # 缺失的一侧（如图层里只有「女士」）克隆已有样式补全选项
        if options:
            base = options[0]
            for opt in rule["options"]:
                if all(o["text"] != opt["text"] for o in options):
                    o = dict(base)
                    o["text"] = opt["text"]
                    o["layerName"] = None
                    options.append(o)
        options.sort(key=lambda o: [x["text"] for x in rule["options"]].index(o["text"]))
        rule_hits.append((rule, options))
    if not rule_hits:
        return []
    # 同组合并：多条规则命中 → 一个点选字段囊括全部选项，永远只渲染选中的一个
    groups = {}
    group_order = []
    for rule, options in rule_hits:
        g = rule.get("group") or rule["id"]
        if g not in groups:
            groups[g] = []
            group_order.append(g)
        groups[g].append((rule, options))
    fields = []
    for g in group_order:
        hits = groups[g]
        all_options = []
        for _rule, options in hits:
            all_options += options
        first = all_options[0]
        if len(hits) == 1:
            rule = hits[0][0]
            fields.append({
                "id": rule["id"], "type": "choice", "label": rule["label"],
                "text": first["text"], "options": all_options, "variable": True,
                "family": None,
            })
        else:
            fields.append({
                "id": g, "type": "choice", "label": GROUP_LABELS.get(g, g),
                "text": first["text"], "options": all_options, "variable": True,
                "family": None,
            })
    return fields


def _field_from_layer(fid, label, L, variable):
    bbox = L.get("bbox") or [0, 0, 200, 80]
    w = max(1, bbox[2] - bbox[0])
    align = L.get("align") or "center"
    if align == "left":
        x = bbox[0]
    elif align == "right":
        x = bbox[2]
    else:
        x = round((bbox[0] + bbox[2]) / 2)
    return {
        "id": fid,
        "label": label,
        "text": L["text"],
        "x": x,
        "y": round((bbox[1] + bbox[3]) / 2),
        "fontSize": L["fontSize"] or 60,
        "color": L["color"],
        "family": None,  # 由页面按模板字体填充
        "align": align,
        "baseline": "middle",
        "letterSpacing": round((L.get("tracking") or 0) / 1000 * (L["fontSize"] or 60), 2),
        "lineHeight": 1.5,
        "autoShrink": variable,
        "maxWidth": round(w * 1.4) if variable else None,
        "variable": variable,
        "layerName": L["layerName"],
        "fontPS": L["fontPS"],
    }


def _build_config_draft(name, layers, font_file):
    matched = _match_layers(layers)
    fields = []
    used = set()
    for fid in ("name", "title", "date"):
        if fid in matched:
            fields.append(_field_from_layer(fid, FIELD_LABELS[fid], matched[fid], True))
            used.add(fid)
    fields += _choice_fields(layers)  # 会把命中的图层标记为已消费
    bi = 0
    for L in layers:  # 下划线填空层：「尊敬的______：」→ 只填空位，下划线保留
        if L.get("matched") or not L.get("visible", True):
            continue
        m = BLANK_RE.search(L["text"])
        if not m:
            continue
        bi += 1
        f = _field_from_layer(f"blank{bi}", "填空", L, True)
        f.update({
            "type": "fill",
            "prefix": L["text"][: m.start()],
            "blank": m.group(),
            "suffix": L["text"][m.end():],
            "text": "",  # 默认不填，纯下划线
            "blankMode": "overlay",
            "autoShrink": False,
            "maxWidth": None,
            "label": (L["text"][: m.start()].strip() or L["text"][m.end():].strip() or "填空")[:8],
        })
        L["matched"] = f["id"]
        fields.append(f)
    si = 0
    for L in layers:
        if L.get("matched"):
            continue
        if not L.get("visible", True):
            continue  # 设计里刻意隐藏的图层不生成字段
        si += 1
        f = _field_from_layer(f"s{si}", f"固定文字{si}", L, False)
        f["label"] = L["text"][:8]  # 表单里由前端加「固定·」前缀
        fields.append(f)
    family = Path(font_file).stem if font_file else None
    for f in fields:
        f["family"] = family
    var_ids = [f["id"] for f in fields if f["variable"]]
    return {
        "title": name,
        "outputPrefix": name,
        "fonts": [{"family": family, "file": font_file}] if font_file else [],
        "batch": {"delimiter": "/", "fields": var_ids[:1] or ["name"]},
        "exportWidths": [{"label": "原图分辨率", "width": None}, {"label": "微信 1080px", "width": 1080}],
        "fields": fields,
    }


def _generate_thumbnail(out_dir: Path):
    """从 reference.png 生成轻量 360x640 JPG，供模板切换即时预览。"""
    from PIL import Image

    src = out_dir / "reference.png"
    if not src.exists():
        src = out_dir / "background.png"
    if not src.exists():
        return
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((360, 640), Image.Resampling.LANCZOS)
        im.save(out_dir / "thumbnail.jpg", "JPEG", quality=78, optimize=True, progressive=True)


def _composite_psd(psd, layers, out_dir: Path):
    """生成 background.png（隐藏全部文字层）、reference.png（整图）和 thumbnail.jpg。"""
    warnings = []
    try:
        img = psd.composite(layer_filter=lambda l: getattr(l, "kind", None) != "type")
        if img is not None:
            img.convert("RGBA").save(out_dir / "background.png")
        else:
            warnings.append("背景板合成返回空，请手动导出（隐藏全部文字图层后另存 PNG）")
    except Exception as e:
        warnings.append(f"背景板自动合成失败（{e}），可手动导出：隐藏全部文字图层另存为 background.png")
    try:
        img = psd.composite()
        if img is not None:
            img.convert("RGBA").save(out_dir / "reference.png")
    except Exception as e:
        warnings.append(f"参考图合成失败（{e}），校准叠加不可用（不影响出图）")
    try:
        _generate_thumbnail(out_dir)
    except Exception as e:
        warnings.append(f"缩略图生成失败（{e}），不影响模板使用")
    return warnings


def _template_asset_version(tid: str) -> str:
    tdir = TEMPLATES_DIR / tid
    mtimes = []
    for name in ("background.png", "reference.png", "thumbnail.jpg"):
        p = tdir / name
        try:
            mtimes.append(p.stat().st_mtime_ns)
        except OSError:
            pass
    return str(max(mtimes, default=0))


def _load_templates_index():
    if TEMPLATES_INDEX.exists():
        try:
            return json.loads(TEMPLATES_INDEX.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_templates_index(items):
    TEMPLATES_INDEX.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _find_best_font(layers) -> str | None:
    """按 PSD 字体 PostScript 名在已上传字体里找最像的文件"""
    fonts = _list_fonts()
    if not fonts:
        return None
    ps_names = {_clean_font_name(L["fontPS"]) for L in layers if L.get("fontPS")}
    for fn in fonts:
        stem = Path(fn).stem
        if _clean_font_name(stem) in ps_names:
            return fn
    return fonts[0]


def _list_fonts():
    return sorted(
        p.name for p in FONTS_DIR.iterdir()
        if p.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2", ".ttc")
    )


# ---------------------------------------------------------------- 基础路由


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(ROOT / "admin.html")


class PasswordVerifyResp(BaseModel):
    ok: bool


@app.post("/api/verify-password")
def verify_password(req: PasswordReq):
    """页面密码校验（字段匹配/删除模板按钮用）"""
    if req.password == PAGE_PASSWORD:
        return PasswordVerifyResp(ok=True)
    raise HTTPException(401, "密码错误")


@app.post("/api/export")
def export_pngs(req: ExportReq, request: Request):
    saved = []
    for item in req.items:
        stem = _safe_name(item.filename)
        if stem.lower().endswith(".png"):
            stem = stem[:-4]
        path = OUTPUT / f"{stem}.png"
        i = 1
        while path.exists():
            path = OUTPUT / f"{stem}-{i}.png"
            i += 1
        b64 = item.dataUrl.split(",", 1)[1]
        path.write_bytes(base64.b64decode(b64))
        saved.append(path.name)
    if saved:
        _log_event(
            request, "export",
            visitor=(req.visitor or "")[:64],
            template=(req.template or "")[:64],
            files=saved, count=len(saved),
        )
    return {"saved": saved, "dir": str(OUTPUT), "urls": [f"/output/{n}" for n in saved]}


@app.post("/api/export-zip")
def export_zip(request: Request, data: dict):
    """把已导出的 PNG 打包成 zip 下载（names 为 output 里的文件名）"""
    names = data.get("names") or []
    buf = io.BytesIO()
    packed = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            p = (OUTPUT / _safe_name(n)).with_suffix(".png")
            if OUTPUT.resolve() not in p.resolve().parents:
                continue
            if p.exists():
                z.write(p, p.name)
                packed += 1
    if not packed:
        raise HTTPException(404, "没有可打包的文件")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=invite_{int(time.time())}.zip"},
    )


@app.get("/api/logs")
def get_logs(request: Request, limit: int = 2000):
    """导出统计（仅管理钥匙可见）"""
    _check_admin(request)
    rows = _read_log_rows()
    exports = [r for r in rows if r.get("event") == "export"]
    today = datetime.now().strftime("%Y-%m-%d")
    summary = {
        "total_events": len(exports),
        "total_pngs": sum(int(r.get("count") or 0) for r in exports),
        "today_pngs": sum(int(r.get("count") or 0) for r in exports
                          if str(r.get("time", "")).startswith(today)),
        "visitors": len({r.get("visitor") for r in exports if r.get("visitor")}),
        "templates": sorted({r.get("template") for r in exports if r.get("template")}),
    }
    return {"rows": rows[-max(1, limit):], "total_rows": len(rows), "summary": summary}


@app.get("/api/logs/csv")
def get_logs_csv(request: Request):
    _check_admin(request)
    rows = _read_log_rows()
    cols = ["time", "event", "visitor", "ip", "template", "files", "count", "ua"]
    lines = [",".join(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, list):
                v = ";".join(str(x) for x in v)
            v = str(v).replace('"', '""')
            cells.append(f'"{v}"')
        lines.append(",".join(cells))
    body = "\ufeff" + "\n".join(lines)  # BOM 便于 Excel 直接打开
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=invite_log.csv"},
    )


# ---------------------------------------------------------------- 字体


@app.get("/api/fonts")
def list_fonts():
    return _list_fonts()


@app.post("/api/fonts")
async def upload_fonts(request: Request, files: list[UploadFile] = File(...)):
    _check_admin(request)
    saved = []
    for f in files:
        name = _safe_name(Path(f.filename).name)
        if Path(name).suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2", ".ttc"):
            continue
        (FONTS_DIR / name).write_bytes(await f.read())
        saved.append(name)
    if not saved:
        raise HTTPException(400, "没有可识别的字体文件（支持 ttf/otf/woff/woff2/ttc）")
    _log_event(request, "fonts", files=saved)
    return {"saved": saved}


# ---------------------------------------------------------------- 模板


@app.get("/api/templates")
def list_templates():
    items = _load_templates_index()
    return [{**t, "assetVersion": _template_asset_version(t["id"])} for t in items]


BACKUP_VERSION = 1
MAX_BACKUP_UPLOAD = 300 * 1024 * 1024
ALLOWED_TEMPLATE_FILES = {"config.json", "layers.json", "source.psd", "background.png", "reference.png", "thumbnail.jpg"}


def _template_used_fonts(config: dict) -> set[str]:
    return {Path(f["file"]).name for f in config.get("fonts", []) if f.get("file")}


@app.post("/api/templates/backup")
def backup_templates(req: BackupReq, request: Request):
    _check_admin(request)
    _check_page_password(request)
    all_items = _load_templates_index()
    wanted = set(req.names)
    selected = [t for t in all_items if not wanted or t.get("name") in wanted]
    if not selected:
        raise HTTPException(404, "没有匹配的模板")
    buf = io.BytesIO()
    manifest = {"format": "web-invite-template-backup", "version": BACKUP_VERSION, "templates": []}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for meta in selected:
            tid = meta["id"]
            tdir = TEMPLATES_DIR / tid
            cfg_path = tdir / "config.json"
            if not cfg_path.exists():
                continue
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            manifest["templates"].append({"id": tid, "name": meta.get("name") or cfg.get("title") or tid})
            for filename in sorted(ALLOWED_TEMPLATE_FILES):
                p = tdir / filename
                if p.is_file():
                    z.write(p, f"templates/{tid}/{filename}")
            for font in _template_used_fonts(cfg):
                p = FONTS_DIR / font
                if p.is_file():
                    z.write(p, f"fonts/{font}")
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buf.seek(0)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=web-invite-template-backup.zip"})


@app.post("/api/templates/restore")
async def restore_templates(file: UploadFile = File(...), request: Request = None):
    _check_admin(request)
    _check_page_password(request)
    data = await file.read()
    if len(data) > MAX_BACKUP_UPLOAD:
        raise HTTPException(413, "备份 ZIP 超过 300MB 限制")
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "文件不是有效 ZIP")
    with zin:
        infos = zin.infolist()
        if len(infos) > 1000:
            raise HTTPException(400, "ZIP 文件项过多")
        total = 0
        safe = {}
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = name.split("/")
            if name.startswith("/") or any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
                raise HTTPException(400, "ZIP 含不安全路径")
            total += info.file_size
            if total > MAX_BACKUP_UPLOAD:
                raise HTTPException(413, "解压内容超过 300MB 限制")
            safe[name] = info
        if "manifest.json" not in safe:
            raise HTTPException(400, "缺少 manifest.json")
        try:
            manifest = json.loads(zin.read(safe["manifest.json"]))
        except Exception:
            raise HTTPException(400, "manifest.json 无法解析")
        if manifest.get("format") != "web-invite-template-backup" or manifest.get("version") != BACKUP_VERSION:
            raise HTTPException(400, "不支持的模板备份格式/版本")
        entries = manifest.get("templates", [])
        if not isinstance(entries, list) or not entries or len(entries) > 100:
            raise HTTPException(400, "备份模板清单为空或数量过多")
        if len({str(e.get("id", "")) for e in entries if isinstance(e, dict)}) != len(entries):
            raise HTTPException(400, "备份模板清单含重复或无效 ID")
        restored = []
        staged = []
        existing_ids = {x.get("id") for x in _load_templates_index()}
        planned_ids = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise HTTPException(400, "模板清单格式无效")
            old_id = str(entry.get("id", ""))
            if not re.fullmatch(r"t[0-9A-Za-z_-]{1,64}", old_id):
                raise HTTPException(400, "模板清单 ID 无效")
            prefix = f"templates/{old_id}/"
            files = {}
            for name in safe:
                if name.startswith(prefix):
                    rel = name[len(prefix):]
                    if "/" in rel or rel not in ALLOWED_TEMPLATE_FILES:
                        raise HTTPException(400, "模板备份含未知文件")
                    files[rel] = safe[name]
            if "config.json" not in files or "background.png" not in files:
                raise HTTPException(400, f"模板 {entry.get('name', old_id)} 缺少必需文件")
            try:
                cfg = json.loads(zin.read(files["config.json"]))
            except Exception:
                raise HTTPException(400, "模板 config.json 无法解析")
            if not isinstance(cfg.get("fields", []), list) or not isinstance(cfg.get("fonts", []), list):
                raise HTTPException(400, "模板配置结构无效")
            for font_name in _template_used_fonts(cfg):
                if Path(font_name).name != font_name or "/" in font_name or "\\" in font_name:
                    raise HTTPException(400, "模板字体路径无效")
            new_id = f"t{int(time.time() * 1000) % 10**10}{len(staged):02d}"
            while new_id in existing_ids or new_id in planned_ids or (TEMPLATES_DIR / new_id).exists():
                new_id = f"t{int(time.time() * 1000) % 10**10}{len(staged) + len(planned_ids) + 1:02d}"
            planned_ids.add(new_id)
            new_name = _safe_name(entry.get("name") or cfg.get("title") or "恢复模板")
            cfg["title"] = new_name
            cfg["outputPrefix"] = new_name
            staged.append({"id": new_id, "name": new_name, "config": cfg, "files": files})
        restored = []
        for item in staged:
            new_id, new_name, cfg, files = item["id"], item["name"], item["config"], item["files"]
            new_dir = TEMPLATES_DIR / new_id
            new_dir.mkdir(parents=True, exist_ok=False)
            for rel, info in files.items():
                (new_dir / rel).write_bytes(zin.read(info))
            (new_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            for font_name in _template_used_fonts(cfg):
                font_info = safe.get(f"fonts/{font_name}")
                if font_info:
                    (FONTS_DIR / font_name).write_bytes(zin.read(font_info))
            restored.append({"id": new_id, "name": new_name, "createdAt": time.strftime("%Y-%m-%d %H:%M")})
    items = _load_templates_index()
    items.extend(restored)
    _save_templates_index(items)
    _log_event(request, "restore", count=len(restored), templates=[t["name"] for t in restored])
    return {"ok": True, "templates": restored}


@app.post("/api/templates")
async def upload_template(request: Request, name: str = Form(""), file: UploadFile = File(...)):
    _check_admin(request)
    tpl_name = _safe_name(name or Path(file.filename).stem or "未命名模板")
    tid = f"t{int(time.time() * 1000) % 10**10}"
    tdir = TEMPLATES_DIR / tid
    tdir.mkdir(parents=True, exist_ok=True)

    psd_path = tdir / "source.psd"
    psd_path.write_bytes(await file.read())

    psd, layers, warnings = _analyze_psd(psd_path)
    font_file = _find_best_font(layers)
    config = _build_config_draft(tpl_name, layers, font_file)
    warnings += _composite_psd(psd, layers, tdir)

    (tdir / "layers.json").write_text(
        json.dumps(layers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tdir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = {"id": tid, "name": tpl_name, "createdAt": time.strftime("%Y-%m-%d %H:%M")}
    items = _load_templates_index()
    items.append(meta)
    _save_templates_index(items)
    _log_event(request, "upload", template=tpl_name, tid=tid,
               layers=len(layers), warnings=warnings)
    return {**meta, "layers": layers, "config": config, "warnings": warnings}


@app.get("/api/templates/{tid}/config")
def get_template_config(tid: str):
    p = TEMPLATES_DIR / tid / "config.json"
    if not p.exists():
        raise HTTPException(404, "模板不存在")
    return FileResponse(p, media_type="application/json", headers={"Cache-Control": "no-store"})


@app.post("/api/templates/{tid}/config")
def save_template_config(tid: str, data: dict, request: Request):
    _check_admin(request)
    tdir = TEMPLATES_DIR / tid
    if not tdir.exists():
        raise HTTPException(404, "模板不存在")
    (tdir / "config.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@app.get("/api/templates/{tid}/layers")
def get_template_layers(tid: str):
    p = TEMPLATES_DIR / tid / "layers.json"
    if not p.exists():
        raise HTTPException(404, "模板不存在")
    return FileResponse(p, media_type="application/json", headers={"Cache-Control": "no-store"})


@app.post("/api/templates/{tid}/duplicate")
def duplicate_template(tid: str, request: Request, name: str = Form("")):
    """复制模板：整目录拷贝（背景板/参考图/配置沿用），改名为新模板"""
    _check_admin(request)
    src = TEMPLATES_DIR / tid
    if not (src / "config.json").exists():
        raise HTTPException(404, "模板不存在")
    new_name = _safe_name(name) or "模板副本"
    new_id = f"t{int(time.time() * 1000) % 10**10}"
    shutil.copytree(src, TEMPLATES_DIR / new_id)
    cfg_path = TEMPLATES_DIR / new_id / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["title"] = new_name
        cfg["outputPrefix"] = new_name
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    meta = {"id": new_id, "name": new_name, "createdAt": time.strftime("%Y-%m-%d %H:%M")}
    items = _load_templates_index()
    items.append(meta)
    _save_templates_index(items)
    _log_event(request, "copy", template=new_name, tid=new_id, src=tid)
    return meta


@app.post("/api/templates/{tid}/reanalyze")
def reanalyze_template(tid: str, request: Request):
    """用最新解析规则重跑已有模板的 source.psd（升级识别能力后无需重传）"""
    _check_admin(request)
    tdir = TEMPLATES_DIR / tid
    psd_path = tdir / "source.psd"
    if not psd_path.exists():
        raise HTTPException(404, "缺少 source.psd")
    cfg_old = {}
    cp = tdir / "config.json"
    if cp.exists():
        try:
            cfg_old = json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    name = cfg_old.get("title") or tid
    font_file = (cfg_old.get("fonts") or [{}])[0].get("file") or _find_best_font([])
    psd, layers, warnings = _analyze_psd(psd_path)
    config = _build_config_draft(name, layers, font_file)
    warnings += _composite_psd(psd, layers, tdir)
    (tdir / "layers.json").write_text(
        json.dumps(layers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tdir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _log_event(request, "reanalyze", template=name, tid=tid, layers=len(layers))
    return {"ok": True, "layers": layers, "config": config, "warnings": warnings}


@app.delete("/api/templates/{tid}")
def delete_template(tid: str, request: Request):
    _check_admin(request)
    tdir = TEMPLATES_DIR / tid
    name = ""
    if tdir.exists():
        cfg = tdir / "config.json"
        if cfg.exists():
            try:
                name = json.loads(cfg.read_text(encoding="utf-8")).get("title", "")
            except Exception:
                pass
        shutil.rmtree(tdir)
    items = [t for t in _load_templates_index() if t["id"] != tid]
    _save_templates_index(items)
    _log_event(request, "delete", template=name, tid=tid)
    return {"ok": True}


app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
app.mount("/vendor", StaticFiles(directory=ROOT / "vendor"), name="vendor")
app.mount("/output", StaticFiles(directory=OUTPUT), name="output")


def _open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    import uvicorn

    if "--no-open" not in sys.argv:
        threading.Timer(1.5, _open_browser).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
