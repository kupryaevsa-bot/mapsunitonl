# -*- coding: utf-8 -*-
"""Паспорт и выгрузка сектора №56 рабочего региона 12×13.

Сектор №56 = x 700–799, y 400–499 (нумерация региона слева-направо, сверху-вниз).
Тот же квадрат в диагональном атласе — кадр №16 «Кирпичный квартал».

Делает в exports/sector_56_x700-799_y400-499/:
  sector_56.json            — все элементы: тайлы, объекты, спрайты + сводка
  sector_56_tiles.csv       — 2500 тайлов земли
  sector_56_objects.csv     — 1856 объектов
  sector_56_sprites.csv     — 3890 спрайтов объектов
  sector_56_screenshot_hq.png — свежий рендер сектора (изометрия, HQ)
  sector_56_screenshot.jpg    — тот же рендер, JPEG
  sector_56_atlas_1531x817.jpg — готовая вырезка из атласа map_book/sectors
  sector_56_packs.png       — каталог элементов: паки спрайтов
  sector_56_tiles_palette.png — все 115 тайлов земли сектора
  how_tiles_assemble.png    — схема: как тайл и объект встают в изометрию
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from farm.export_assembly_region import (  # noqa: E402
    DRAW_H,
    DRAW_W,
    HALF_H,
    HALF_W,
    LEVEL_H,
    _bg_path,
    _open_img,
    _rp_path,
    export_region,
    filter_region,
    grid_to_screen,
    load_memory,
    sprite_ok,
)

OUT = BASE / "exports" / "sector_56_x700-799_y400-499"
TILES_ROOT = BASE / "static" / "tiles"
SECTOR_N = 56
X0, Y0, X1, Y1 = 700, 400, 799, 499
REGION = {"x0": 0, "y0": 0, "x1": 1199, "y1": 1299, "cols": 12, "rows": 13}
SECTOR_NAME = "Кирпичный квартал"
ATLAS_FRAME = BASE / "map_book" / "sectors" / "sector_x0700_y0400.jpg"
FONT_R = r"C:\Windows\Fonts\consola.ttf"
FONT_B = r"C:\Windows\Fonts\consolab.ttf"

# имена паков из словаря проекта (make_diag_doc.py / landmarks.py)
PACK_NAMES = {
    0: "кованый забор", 1: "сетка-рабица", 3: "руины стен", 4: "асфальт",
    5: "щиты и вывески", 6: "плитка/бетон", 7: "осеннее дерево", 10: "фонтан",
    15: "камень/плиты", 16: "билборд", 20: "деревянный настил", 23: "вывеска SPAR",
    24: "фонари", 25: "навесы и крыши", 26: "крыши", 40: "беседка",
    43: "колодец/башня", 47: "лиственные деревья", 48: "столбы", 49: "разбитая машина",
    60: "каменные площадки", 63: "обломки/щебень", 64: "балки и рельсы",
    68: "кусты", 69: "кусты/сухостой", 71: "кусты", 72: "трава", 73: "трава/камыш",
    77: "навес/рынок", 78: "лестница", 81: "машина", 83: "деревянные настилы",
    84: "ангар", 87: "статуя", 93: "лестницы", 94: "решётки", 95: "рельсы",
    96: "шпиль", 104: "контейнеры/декор", 107: "саженцы", 110: "высокая трава",
    113: "вышка", 125: "ели", 134: "модули построек", 136: "кусты", 137: "вода/камни",
    138: "сухостой",
    # уточнено по каталогу спрайтов самого сектора №56
    14: "обломки/предметы", 31: "кирпичная кладка", 39: "брусчатка",
    53: "кирпичный фасад", 54: "кирпичный фасад", 55: "окна/двери",
    90: "витрины/стенды", 118: "бетонная панель", 119: "скамейки",
}


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_B if bold else FONT_R, size)
    except Exception:
        return ImageFont.load_default()


def pack_label(p: int) -> str:
    return PACK_NAMES.get(int(p), f"pack {int(p)}")


def fit_text(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: int) -> str:
    """Обрезать подпись с многоточием, чтобы влезла в ячейку."""
    f = font(size, True)
    if draw.textlength(text, font=f) <= max_w:
        return text
    cut = text
    while cut and draw.textlength(cut + "…", font=f) > max_w:
        cut = cut[:-1]
    return cut + "…"


def in_sector(i: int, j: int) -> bool:
    """Та же выборка, что filter_region (допуск 1/4 клетки)."""
    x, y = j / 2.0, i / 2.0
    return X0 - 0.25 <= x <= X1 + 0.25 and Y0 - 0.25 <= y <= Y1 + 0.25


# ---------------------------------------------------------------- данные
def load_sector() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    raw = json.loads((BASE / "world_memory.json").read_text(encoding="utf-8"))
    tiles_all = list(raw.get("tiles") or [])
    objs_all = list(raw.get("objects") or [])
    tiles, objects = filter_region(tiles_all, objs_all, X0, Y0, X1, Y1)
    # ручная отметка «готово» и точки, где персонаж реально стоял
    ready = {(int(a), int(b)) for a, b in (raw.get("manual_ready") or [])}
    raw_stood = raw.get("stood") or []
    stood = []
    for row in raw_stood:
        try:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                stood.append((int(row[0]), int(row[1])))
            elif isinstance(row, dict):
                stood.append((int(row["x"]), int(row["y"])))
        except (TypeError, ValueError):
            continue
    return tiles, objects, {
        "updated_at": raw.get("updated_at"),
        "map_w": raw.get("map_w"),
        "map_h": raw.get("map_h"),
        "level_h": raw.get("level_h"),
        "sb_ok": raw.get("sb_ok"),
        "ol_ok": raw.get("ol_ok"),
        "manual_ready": ready,
        "stood": stood,
        "source_tiles": len(tiles_all),
        "source_objects": len(objs_all),
    }


def classify_objects(objects: List[Dict[str, Any]]) -> Dict[int, str]:
    """Категория объекта — та же эвристика, что map_book/obj_categories.py."""
    cache_path = BASE / "map_book" / "sprite_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}

    def sig_info(o):
        sp = o.get("sprites") or []
        if not sp:
            return None
        minx = miny = 10 ** 9
        maxx = maxy = -(10 ** 9)
        rs = gs = bs = area = 0
        for s in sp:
            key = f"{int(s['pack'])}_{int(s['image'])}"
            c = cache.get(key)
            if not c:
                continue
            fw = c[0] // max(1, int(s.get("frames") or 1))
            ox, oy = int(s.get("ox") or 0), int(s.get("oy") or 0)
            minx = min(minx, ox)
            miny = min(miny, oy)
            maxx = max(maxx, ox + fw)
            maxy = max(maxy, oy + c[1])
            a = fw * c[1]
            rs += c[2] * a
            gs += c[3] * a
            bs += c[4] * a
            area += a
        if area == 0:
            return None
        return {"n": len(sp), "w": maxx - minx, "h": maxy - miny,
                "rgb": (rs // area, gs // area, bs // area)}

    def classify(info):
        n, w, h = info["n"], info["w"], info["h"]
        r, g, b = info["rgb"]
        green = g > r * 1.06 and g > b * 1.10
        gray = abs(r - g) < 18 and abs(g - b) < 18
        if n >= 8:
            return "здание/сооружение"
        if h <= 26 and w >= 48:
            return "покрытие/декаль"
        if green and h >= 28:
            return "растительность"
        if gray and h >= 24:
            return "камень/руины"
        if green:
            return "трава/кусты"
        if gray:
            return "камень мелкий"
        return "декор/предмет"

    out = {}
    sig_cat = {}
    for o in objects:
        key = tuple((int(s["pack"]), int(s["image"]), int(s.get("ox") or 0), int(s.get("oy") or 0))
                    for s in (o.get("sprites") or []))
        c = sig_cat.get(key)
        if c is None:
            info = sig_info(o)
            c = classify(info) if info else "?"
            sig_cat[key] = c
        out[int(o["oid"])] = c
    return out


def sprite_size(pack: int, image: int) -> Optional[Tuple[int, int]]:
    try:
        with Image.open(_rp_path(pack, image)) as im:
            return im.width, im.height
    except Exception:
        return None


def build_elements(tiles, objects, meta) -> Dict[str, Any]:
    cats = classify_objects(objects)
    block_ids = json.loads((BASE / "map_book" / "blocks.json").read_text(encoding="utf-8"))["ids"]

    tile_rows = []
    for t in tiles:
        i, j, lvl, tid = int(t["i"]), int(t["j"]), int(t["level"]), int(t["id"])
        x, y = j // 2, i // 2
        cat = (block_ids.get(str(tid)) or {}).get("cat", "?")
        tile_rows.append({
            "i": i, "j": j, "x": x, "y": y, "level": lvl, "id": tid, "cat": cat,
            "png": f"static/tiles/bg/IMAGE_{tid}.png",
        })

    obj_rows = []
    for o in objects:
        i, j, lvl = int(o["i"]), int(o["j"]), int(o.get("level") or 0)
        x, y = j // 2, i // 2
        sprites = []
        for s in o.get("sprites") or []:
            pack, image = int(s["pack"]), int(s["image"])
            frames = max(1, int(s.get("frames") or 1))
            size = sprite_size(pack, image)
            sp = {
                "pack": pack, "image": image,
                "ox": int(s.get("ox") or 0), "oy": int(s.get("oy") or 0),
                "frames": frames, "hide": int(s.get("hide") or 0),
                "png": f"static/tiles/rp/{pack}/IMAGE_{image}.png",
                "file_ok": size is not None,
                "drawable": sprite_ok(s),
            }
            if size:
                sp["png_w"], sp["png_h"] = size
                sp["frame_w"] = max(1, size[0] // frames)
            sprites.append(sp)
        obj_rows.append({
            "oid": int(o["oid"]), "i": i, "j": j, "x": x, "y": y,
            "level": lvl, "depth": int(o.get("depth") or 0), "type": str(o.get("type") or ""),
            "category": cats.get(int(o["oid"]), "?"),
            "n_sprites": len(sprites),
            "sprites": sprites,
        })

    # --- сводка по земле ---
    tile_levels = Counter(r["level"] for r in tile_rows)
    tile_ids = Counter(r["id"] for r in tile_rows)
    cat_by_id = {r["id"]: r["cat"] for r in tile_rows}
    ground_cats = Counter()
    for r in tile_rows:
        ground_cats[r["cat"]] += 1
    cells = {(r["x"], r["y"]) for r in tile_rows}
    holes = 0
    for x in range(X0, X0 + 100, 2):
        for y in range(Y0, Y0 + 100, 2):
            if (x, y) not in cells:
                n = sum(1 for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
                        if (x + dx, y + dy) in cells)
                if n >= 2:
                    holes += 1
    id0 = sum(1 for r in tile_rows if r["id"] == 0)
    ground = {
        "tile_count": len(tile_rows),
        "filled_cells": len(cells),
        "expected_cells": 50 * 50,
        "coverage_pct": round(100.0 * len(cells) / (50 * 50), 2),
        "holes": holes,
        "id0_tiles": id0,
        "levels": {str(k): v for k, v in sorted(tile_levels.items())},
        "unique_ids": len(tile_ids),
        "by_category": {k: v for k, v in ground_cats.most_common()},
        "by_category_pct": {
            k: round(100.0 * v / len(tile_rows), 2) for k, v in ground_cats.most_common()
        },
        "top_ids": [
            {"id": tid, "count": n, "cat": cat_by_id.get(tid, "?"),
             "share_pct": round(100.0 * n / len(tile_rows), 2),
             "png": f"static/tiles/bg/IMAGE_{tid}.png"}
            for tid, n in tile_ids.most_common(20)
        ],
    }

    # --- сводка по объектам ---
    obj_levels = Counter(r["level"] for r in obj_rows)
    obj_types = Counter(r["type"] for r in obj_rows)
    obj_cats = Counter(r["category"] for r in obj_rows)
    pack_cnt = Counter()
    pack_imgs = defaultdict(set)
    for r in obj_rows:
        for s in r["sprites"]:
            pack_cnt[s["pack"]] += 1
            pack_imgs[s["pack"]].add(s["image"])
    packs = [
        {"pack": p, "name": pack_label(p), "sprites": n, "images": len(pack_imgs[p])}
        for p, n in pack_cnt.most_common()
    ]
    sizes = [r["n_sprites"] for r in obj_rows]
    hist = Counter()
    for n in sizes:
        if n == 1:
            hist["1"] += 1
        elif n == 2:
            hist["2"] += 1
        elif n <= 5:
            hist["3-5"] += 1
        elif n <= 10:
            hist["6-10"] += 1
        elif n <= 30:
            hist["11-30"] += 1
        else:
            hist["31+"] += 1
    biggest = sorted(obj_rows, key=lambda r: -r["n_sprites"])[:15]
    biggest_out = [
        {"oid": r["oid"], "x": r["x"], "y": r["y"], "level": r["level"],
         "n_sprites": r["n_sprites"], "packs": sorted({s["pack"] for s in r["sprites"]}),
         "category": r["category"]}
        for r in biggest
    ]
    drawable_sp = sum(1 for r in obj_rows for s in r["sprites"] if s["drawable"])
    missing_files = sum(1 for r in obj_rows for s in r["sprites"] if not s["file_ok"])
    objects_summary = {
        "count": len(obj_rows),
        "sprites": sum(len(r["sprites"]) for r in obj_rows),
        "sprites_drawable": drawable_sp,
        "sprites_hidden": sum(1 for r in obj_rows for s in r["sprites"] if not s["drawable"]),
        "missing_sprite_files": missing_files,
        "by_level": {str(k): v for k, v in sorted(obj_levels.items())},
        "by_type": dict(obj_types.most_common()),
        "by_category": dict(obj_cats.most_common()),
        "size_hist": dict(hist),
        "packs": packs,
        "biggest": biggest_out,
    }

    # --- готовность (как считает приложение) ---
    stood_in = [(x, y) for x, y in meta["stood"] if X0 <= x <= X1 and Y0 <= y <= Y1]
    center = (X0 + 50, Y0 + 50)
    center_stood = any(abs(x - center[0]) <= 6 and abs(y - center[1]) <= 6 for x, y in stood_in)
    ready = (X0, Y0) in meta["manual_ready"]
    updated = meta.get("updated_at")
    try:
        updated_iso = datetime.fromtimestamp(float(updated), timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        updated_iso = ""
    assembly = {
        "coverage_pct": ground["coverage_pct"],
        "filled_cells": ground["filled_cells"],
        "expected_cells": ground["expected_cells"],
        "holes": holes,
        "id0_tiles": id0,
        "manual_ready": ready,
        "center": {"x": center[0], "y": center[1]},
        "center_stood": center_stood,
        "stood_points_in_sector": len(stood_in),
        "app_ready_hint": "сектор числится готовым" if ready else (
            "не отмечен готовым; покрытие 100%, но стояния в центре нет"
            if not center_stood else "не отмечен готовым вручную, условия покрытия и стояния выполнены"),
    }

    payload = {
        "ok": True,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sector": {
            "n": SECTOR_N,
            "n_basis": "56-й сектор рабочего региона 12×13 (x 0–1199, y 0–1299), нумерация слева-направо, сверху-вниз",
            "name_hint": SECTOR_NAME,
            "atlas_frame": "№16 «Кирпичный квартал» в Диагональ_24_сектора_рассказ.docx",
            "region": REGION,
            "x0": X0, "y0": Y0, "x1": X1, "y1": Y1,
            "width_cells": 100, "height_cells": 100,
            "tiles_grid": [50, 50],
            "i0": min(r["i"] for r in tile_rows), "i1": max(r["i"] for r in tile_rows),
            "j0": min(r["j"] for r in tile_rows), "j1": max(r["j"] for r in tile_rows),
            "atlas_image": "map_book/sectors/sector_x0700_y0400.jpg",
        },
        "source": {
            "file": "world_memory.json",
            "updated_at": updated,
            "updated_iso": updated_iso,
            "map_w": meta.get("map_w"), "map_h": meta.get("map_h"),
            "source_tiles": meta.get("source_tiles"), "source_objects": meta.get("source_objects"),
            "sb_ok": meta.get("sb_ok"), "ol_ok": meta.get("ol_ok"),
            "level_h": meta.get("level_h") or LEVEL_H,
        },
        "projection": {
            "screen_x": "sx = (i + j) * 16",
            "screen_y": "sy = (i - j) * 8 - level * 85",
            "tile_paste": "tile draw at (sx - 32, sy - 32), image 128×64",
            "object_paste": "sprite draw at (sx + ox, sy + oy)",
            "half_w": HALF_W, "half_h": HALF_H, "level_h": LEVEL_H,
            "tile_px": [DRAW_W, DRAW_H],
            "tile_step_i": 4, "tile_step_j": 4,
            "tile_covers_cells": "4×4 клетки по 32×16 px",
            "sort_tiles": "level, i+j, i, j (дальние → ближние)",
            "sort_objects": "level, depth, oid",
        },
        "counts": {
            "tiles": len(tile_rows),
            "objects": len(obj_rows),
            "sprites": objects_summary["sprites"],
        },
        "assembly_status": assembly,
        "ground": ground,
        "objects_summary": objects_summary,
        "tiles": tile_rows,
        "objects": obj_rows,
    }
    return payload


# ---------------------------------------------------------------- рендер
def render_sector_png(tiles, objects, out_png: Path, max_side: int = 3600) -> Dict[str, Any]:
    """Изометрический рендер сектора (та же математика, что farm/export_assembly_region)."""
    Image.MAX_IMAGE_PIXELS = None
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS

    pts: List[Tuple[int, int]] = []
    for t in tiles:
        sx, sy = grid_to_screen(int(t["i"]), int(t["j"]), int(t["level"]))
        pts.append((sx - 32, sy - 32))
        pts.append((sx - 32 + DRAW_W, sy - 32 + DRAW_H))
    for o in objects:
        sx, sy = grid_to_screen(int(o["i"]), int(o["j"]), int(o.get("level") or 0))
        for sp in o.get("sprites") or []:
            if not sprite_ok(sp):
                continue
            ox, oy = int(sp.get("ox") or 0), int(sp.get("oy") or 0)
            pts.append((sx + ox - 4, sy + oy - 4))
            pts.append((sx + ox + 80, sy + oy + 80))
    min_x = min(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_x = max(p[0] for p in pts)
    max_y = max(p[1] for p in pts)
    raw_w, raw_h = max(1, max_x - min_x), max(1, max_y - min_y)
    scale = min(1.0, float(max_side) / max(raw_w, raw_h))
    pad = 14
    width = int(raw_w * scale) + pad * 2
    height = int(raw_h * scale) + pad * 2
    canvas = Image.new("RGB", (width, height), (18, 16, 12))

    tw, th = max(2, int(DRAW_W * scale)), max(2, int(DRAW_H * scale))
    tile_cache: Dict[int, Optional[Image.Image]] = {}

    def to_px(sx, sy):
        return int((sx - min_x) * scale) + pad, int((sy - min_y) * scale) + pad

    def paste(im, px, py):
        if im is None:
            return
        canvas.paste(im, (px, py), im)

    def tile_im(tid):
        if tid not in tile_cache:
            src = _open_img(_bg_path(tid))
            tile_cache[tid] = src.resize((tw, th), resample) if src is not None else None
        return tile_cache[tid]

    for t in tiles:
        sx, sy = grid_to_screen(int(t["i"]), int(t["j"]), int(t["level"]))
        px, py = to_px(sx - 32, sy - 32)
        paste(tile_im(int(t["id"])), px, py)

    rp_cache: Dict[Tuple[int, int, int, int], Optional[Image.Image]] = {}
    src_cache: Dict[Tuple[int, int], Optional[Image.Image]] = {}
    drawn_obj = 0
    for o in objects:
        sx, sy = grid_to_screen(int(o["i"]), int(o["j"]), int(o.get("level") or 0))
        any_sp = False
        for sp in o.get("sprites") or []:
            if not sprite_ok(sp):
                continue
            pack, image = int(sp["pack"]), int(sp["image"])
            key = (pack, image)
            if key not in src_cache:
                src_cache[key] = _open_img(_rp_path(pack, image))
            im = src_cache[key]
            if im is None:
                continue
            frames = max(1, int(sp.get("frames") or 1))
            if frames > 64 or im.width % frames:
                frames = 1
            fw = max(1, im.width // frames)
            dw, dh = max(1, int(fw * scale)), max(1, int(im.height * scale))
            ck = (pack, image, dw, dh)
            if ck not in rp_cache:
                rp_cache[ck] = im.crop((0, 0, fw, im.height)).resize((dw, dh), resample)
            ox, oy = int(sp.get("ox") or 0), int(sp.get("oy") or 0)
            px, py = to_px(sx + ox, sy + oy)
            paste(rp_cache[ck], px, py)
            any_sp = True
        drawn_obj += 1 if any_sp else 0

    canvas.save(out_png, "PNG", optimize=True)
    return {
        "width": width, "height": height, "scale": round(scale, 4),
        "tiles": len(tiles), "objects": drawn_obj,
        "bbox": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    }


def frame_screenshot(raw_png: Path, out_png: Path, out_jpg: Path, info: Dict[str, Any]) -> None:
    """Обернуть рендер в рамку с шапкой и подписью (как кадры атласа)."""
    im = Image.open(raw_png).convert("RGB")
    title = f"СЕКТОР №{SECTOR_N}   x {X0}–{X1}   y {Y0}–{Y1}   (100 × 100 клеток = 50 × 50 тайлов)"
    sub = (f"тайлы {info['tiles']} · объекты {info['counts_objects']} · спрайты {info['counts_sprites']} · "
           f"изометрия 2:1 · 1 тайл 128×64 px · 1 этаж 85 px")
    foot = (f"Свежий рендер из world_memory.json · {info['date']} · "
            f"холст {info['width']}×{info['height']} px · масштаб {info['scale']}")
    bar_t, bar_b, pad = 66, 38, 14
    W = im.width + pad * 2
    H = im.height + bar_t + bar_b + pad * 2
    canvas = Image.new("RGB", (W, H), (16, 14, 12))
    d = ImageDraw.Draw(canvas)
    d.text((pad + 4, 12), title, fill=(245, 226, 170), font=font(27, True))
    d.text((pad + 4, 43), sub, fill=(168, 190, 210), font=font(17))
    d.rectangle([pad - 1, bar_t, W - pad - 1, H - bar_b - pad], outline=(120, 104, 80), width=2)
    canvas.paste(im, (pad, bar_t + 1))
    d.text((pad + 4, H - bar_b - 2), foot, fill=(130, 120, 104), font=font(15))
    canvas.save(out_png, "PNG", optimize=True)
    canvas.save(out_jpg, "JPEG", quality=90, subsampling=0, optimize=True)


# ---------------------------------------------------------------- каталоги
def build_packs_sheet(objects, payload, out_png: Path) -> int:
    cache = json.loads((BASE / "map_book" / "sprite_cache.json").read_text(encoding="utf-8"))
    pack_cnt = Counter()
    pack_imgs = defaultdict(set)
    for o in objects:
        for s in o.get("sprites") or []:
            pack_cnt[int(s["pack"])] += 1
            pack_imgs[int(s["pack"])].add(int(s["image"]))
    rows = []
    for p, n in pack_cnt.most_common(24):
        best = None
        for im in sorted(pack_imgs[p]):
            fp = _rp_path(p, im)
            if not fp.is_file():
                continue
            try:
                obj = Image.open(fp).convert("RGBA")
            except Exception:
                continue
            area = obj.width * obj.height
            if best is None or area > best[0]:
                best = (area, im, obj)
        if best:
            rows.append((p, n, best[1], best[2], len(pack_imgs[p])))
    cols, cw, ch = 8, 250, 300
    nrows = (len(rows) + cols - 1) // cols
    header = 74
    sheet = Image.new("RGB", (cols * cw, header + nrows * ch + 10), (24, 22, 18))
    d = ImageDraw.Draw(sheet)
    d.text((18, 14), f"ЭЛЕМЕНТЫ СЕКТОРА №{SECTOR_N} — паки спрайтов (топ-{len(rows)} по числу спрайтов)",
           fill=(245, 226, 170), font=font(25, True))
    d.text((18, 46), "слева: номер пака · имя из словаря проекта · спрайтов в секторе · картинок в паке · пример PNG",
           fill=(168, 190, 210), font=font(16))
    for k, (p, n, im, obj, ni) in enumerate(rows):
        r, c = divmod(k, cols)
        x, y = c * cw, header + r * ch
        d.rectangle([x + 3, y + 3, x + cw - 5, y + ch - 5], outline=(70, 66, 58))
        sc = min((cw - 24) / obj.width, (ch - 120) / obj.height, 1.0)
        im2 = obj.resize((max(1, int(obj.width * sc)), max(1, int(obj.height * sc))), Image.LANCZOS)
        sheet.paste(im2, (x + (cw - im2.width) // 2, y + 8 + (ch - 120 - im2.height) // 2), im2)
        label = fit_text(d, f"pack {p} · {pack_label(p)}", 17, cw - 26)
        d.text((x + 12, y + ch - 92), label, fill=(255, 236, 180), font=font(17, True))
        d.text((x + 12, y + ch - 66), f"спрайтов {n} · картинок {ni}", fill=(160, 205, 255), font=font(15))
        d.text((x + 12, y + ch - 42), f"rp/{p}/IMAGE_{im}.png", fill=(130, 170, 130), font=font(14))
    sheet.save(out_png, "PNG", optimize=True)
    return len(rows)


def build_tiles_sheet(tiles, payload, out_png: Path) -> int:
    cnt = Counter(int(t["id"]) for t in tiles)
    ids = [i for i, _ in cnt.most_common()]
    blocks = json.loads((BASE / "map_book" / "blocks.json").read_text(encoding="utf-8"))["ids"]
    cols, cw, ch = 10, 176, 134
    nrows = (len(ids) + cols - 1) // cols
    header = 70
    sheet = Image.new("RGB", (cols * cw, header + nrows * ch + 10), (24, 22, 18))
    d = ImageDraw.Draw(sheet)
    d.text((18, 12), f"ЗЕМЛЯ СЕКТОРА №{SECTOR_N} — все {len(ids)} тайлов (static/tiles/bg/IMAGE_id.png)",
           fill=(245, 226, 170), font=font(25, True))
    d.text((18, 44), "id · сколько раз · категория блока (blocks.json); ромб 128×64 px",
           fill=(168, 190, 210), font=font(16))
    for k, tid in enumerate(ids):
        r, c = divmod(k, cols)
        x, y = c * cw, header + r * ch
        d.rectangle([x + 2, y + 2, x + cw - 4, y + ch - 4], outline=(70, 66, 58))
        fp = _bg_path(tid)
        if fp.is_file():
            try:
                obj = Image.open(fp).convert("RGBA")
                sheet.paste(obj, (x + (cw - obj.width) // 2, y + 6), obj)
            except Exception:
                pass
        cat = (blocks.get(str(tid)) or {}).get("cat", "?")
        d.text((x + 8, y + ch - 44), f"id {tid} · ×{cnt[tid]}", fill=(255, 236, 180), font=font(15, True))
        d.text((x + 8, y + ch - 24), cat, fill=(160, 205, 255), font=font(14))
    sheet.save(out_png, "PNG", optimize=True)
    return len(ids)


def build_projection_diagram(out_png: Path) -> None:
    """Схема: клетка (i,j) → экран, один тайл 128×64 = 4×4 клетки, этажи по 85 px."""
    W, H = 1980, 880
    img = Image.new("RGB", (W, H), (24, 22, 18))
    d = ImageDraw.Draw(img)
    d.text((22, 14), "КАК ТАЙЛЫ СОБИРАЮТСЯ В КАРТУ — изометрия 2:1 (сектор №56)", fill=(245, 226, 170), font=font(28, True))
    d.text((22, 50), "sx = (i + j) · 16        sy = (i − j) · 8 − level · 85        клетка 32×16 px, тайл 128×64 px",
           fill=(170, 200, 225), font=font(19))
    d.line([(18, 84), (W - 18, 84)], fill=(110, 96, 74), width=2)

    def panel(x0, y0, w, h, title):
        d.rectangle([x0, y0, x0 + w, y0 + h], outline=(86, 76, 60), width=2)
        d.rectangle([x0, y0, x0 + w, y0 + 36], fill=(36, 32, 26))
        d.text((x0 + 10, y0 + 8), title, fill=(235, 215, 160), font=font(18, True))

    def diamond(cx, cy, w=32, h=16):
        return [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]

    # --- панель 1: сетка (i,j) → экран ---
    px, py, pw, ph = 22, 100, 590, 560
    panel(px, py, pw, ph, "1. Клетка (i, j) встаёт ромбом на экран")
    s = 2.4
    ox, oy = px + 74, py + 190
    n = 6
    for i in range(n + 1):
        for j in range(n + 1):
            cx = ox + int((i + j) * 16 * s)
            cy = oy + int((i - j) * 8 * s)
            fill = (52, 66, 48) if (i + j) % 2 == 0 else (47, 60, 44)
            d.polygon(diamond(cx, cy, int(32 * s), int(16 * s)), fill=fill, outline=(96, 116, 88))
    # оси из клетки (0,0)
    cx0, cy0 = ox, oy
    d.line([(cx0 + 8, cy0), (cx0 + int(16 * 4 * s), cy0 + int(8 * 4 * s))], fill=(150, 210, 150), width=3)
    d.text((cx0 + int(16 * 4 * s) + 6, cy0 + int(8 * 4 * s) - 8), "i", fill=(150, 210, 150), font=font(20, True))
    d.line([(cx0 + 8, cy0 - 3), (cx0 + int(16 * 4 * s), cy0 - int(8 * 4 * s))], fill=(230, 180, 120), width=3)
    d.text((cx0 + int(16 * 4 * s) + 6, cy0 - int(8 * 4 * s) - 8), "j", fill=(230, 180, 120), font=font(20, True))
    # подписи клеток
    for (i, j) in ((0, 0), (0, 6), (6, 0), (6, 6)):
        cx = ox + int((i + j) * 16 * s)
        cy = oy + int((i - j) * 8 * s)
        d.text((cx - 14, cy - 7), f"{i},{j}", fill=(255, 226, 150), font=font(13, True))
    d.text((px + 16, py + ph - 96), "шаг +1 по i: +16 px вправо, +8 px вниз", fill=(200, 190, 170), font=font(16))
    d.text((px + 16, py + ph - 70), "шаг +1 по j: +16 px вправо, −8 px вверх", fill=(200, 190, 170), font=font(16))
    d.text((px + 16, py + ph - 40), "клетка на экране — ромб 32×16 px (2:1)", fill=(168, 190, 210), font=font(16))

    # --- панель 2: тайл 128×64 = 4×4 клетки ---
    px2, py2, pw2, ph2 = 632, 100, 660, 560
    panel(px2, py2, pw2, ph2, "2. Один тайл = 4×4 клетки, рисунок 128×64")
    try:
        tile_src = Image.open(_bg_path(33)).convert("RGBA")
    except Exception:
        tile_src = None
    if tile_src is not None:
        tile2 = tile_src.resize((256, 128), Image.LANCZOS)
        img.paste(tile2, (px2 + (pw2 - tile2.width) // 2, py2 + 150), tile2)
        # отдельная клетка того же материала для сравнения
        cell = tile_src.resize((64, 32), Image.LANCZOS)
        img.paste(cell, (px2 + 90, py2 + 380), cell)
        d.text((px2 + 166, py2 + 388), "1 клетка 32×16 px (здесь ×2)", fill=(255, 236, 180), font=font(15, True))
        d.text((px2 + 166, py2 + 410), "4×4 таких клетки = тайл 128×64", fill=(180, 200, 220), font=font(14))
    d.text((px2 + 16, py2 + ph2 - 96), "рисунок тайла 128×64 px кладётся в точку (sx−32, sy−32)", fill=(200, 190, 170), font=font(16))
    d.text((px2 + 16, py2 + ph2 - 70), "соседние тайлы отстоят на 4 по i или j (= 2 клетки по x/y)", fill=(200, 190, 170), font=font(16))
    d.text((px2 + 16, py2 + ph2 - 40), "поэтому 100×100 клеток сектора = 50×50 тайлов = 2500", fill=(168, 190, 210), font=font(16))

    # --- панель 3: этажи ---
    px3, py3, pw3, ph3 = 1306, 100, 652, 560
    panel(px3, py3, pw3, ph3, "3. Этаж поднимает объект на 85 px")
    bx, by = px3 + 230, py3 + 330
    if tile_src is not None:
        b_img = tile_src
    else:
        b_img = None
    for lvl in (0, 1, 2):
        yy = by - lvl * 85
        if b_img:
            img.paste(b_img, (bx, yy), b_img)
        else:
            d.polygon(diamond(bx + 64, yy + 32, 128, 64), fill=(70, 90, 70), outline=(140, 150, 130))
        d.text((bx + 140, yy + 20), f"level {lvl}", fill=(255, 236, 180), font=font(18, True))
        if lvl:
            d.line([(bx + 6, yy + 32), (bx + 6, yy + 32 + 85)], fill=(200, 150, 110), width=2)
            d.text((bx - 72, yy + 66), "85 px", fill=(220, 170, 130), font=font(15, True))
    d.text((px3 + 16, py3 + ph3 - 92), "level из world_memory: земля 0, этажи 1–4 (в секторе есть все)", fill=(200, 190, 170), font=font(16))
    d.text((px3 + 16, py3 + ph3 - 66), "сортировка тайлов: (level, i+j) — дальние рисуются первыми", fill=(200, 190, 170), font=font(16))
    d.text((px3 + 16, py3 + ph3 - 40), "объекты: (level, depth, oid) — ближние перекрывают дальние", fill=(168, 190, 210), font=font(16))

    # нижняя строка
    d.rectangle([22, H - 168, W - 22, H - 24], outline=(86, 76, 60), width=2)
    d.text((36, H - 156), "КОНВЕЙЕР СБОРКИ", fill=(245, 226, 170), font=font(20, True))
    steps = ("дампы (pcap/текст)  →  farm/dump_import.py  →  world_memory.json: тайлы {i,j,level,id} + объекты {oid,i,j,level,depth,type,sprites}  →  "
             "выбор прямоугольника x0..x1, y0..y1 (x=j/2, y=i/2)  →  сортировка  →  изометрия  →  склейка PNG (bg/IMAGE_id + rp/pack/IMAGE_image)  →  JPEG/PNG")
    # перенос по словам
    words = steps.split(" ")
    line = ""
    y = H - 124
    for wd in words:
        test = (line + " " + wd).strip()
        if d.textlength(test, font=font(15)) > W - 70:
            d.text((36, y), line, fill=(205, 195, 175), font=font(15))
            y += 24
            line = wd
        else:
            line = test
    if line:
        d.text((36, y), line, fill=(205, 195, 175), font=font(15))

    img.save(out_png, "PNG", optimize=True)


# ---------------------------------------------------------------- csv
def copy_sector_sprites(tiles, objects) -> Dict[str, Any]:
    """Скопировать в выгрузку только те PNG, которые использует сектор."""
    bg_dir = OUT / "sprites" / "bg"
    rp_dir = OUT / "sprites" / "rp"
    bg_dir.mkdir(parents=True, exist_ok=True)
    rp_dir.mkdir(parents=True, exist_ok=True)
    ids = sorted({int(t["id"]) for t in tiles})
    combos = sorted({(int(s["pack"]), int(s["image"]))
                     for o in objects for s in (o.get("sprites") or [])})
    n_bg = n_rp = 0
    total = 0
    for tid in ids:
        src = _bg_path(tid)
        if src.is_file():
            shutil.copyfile(src, bg_dir / f"IMAGE_{tid}.png")
            n_bg += 1
            total += src.stat().st_size
    for pack, image in combos:
        src = _rp_path(pack, image)
        if src.is_file():
            dst = rp_dir / str(pack)
            dst.mkdir(exist_ok=True)
            shutil.copyfile(src, dst / f"IMAGE_{image}.png")
            n_rp += 1
            total += src.stat().st_size
    return {
        "dir": "sprites",
        "layout": {"ground": "sprites/bg/IMAGE_{id}.png", "objects": "sprites/rp/{pack}/IMAGE_{image}.png"},
        "bg_files": n_bg,
        "rp_files": n_rp,
        "bytes": total,
        "note": "копии ровно тех PNG из static/tiles, которые нужны этому сектору",
    }


def write_csvs(payload, out_tiles: Path, out_objects: Path, out_sprites: Path) -> None:
    with out_tiles.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["i", "j", "x", "y", "level", "id", "cat", "png"])
        for r in payload["tiles"]:
            w.writerow([r["i"], r["j"], r["x"], r["y"], r["level"], r["id"], r["cat"], r["png"]])
    with out_objects.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["oid", "i", "j", "x", "y", "level", "depth", "type", "category", "n_sprites"])
        for r in payload["objects"]:
            w.writerow([r["oid"], r["i"], r["j"], r["x"], r["y"], r["level"], r["depth"],
                        r["type"], r["category"], r["n_sprites"]])
    with out_sprites.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["oid", "level", "pack", "pack_name", "image", "ox", "oy", "frames", "hide", "png", "drawable"])
        for r in payload["objects"]:
            for s in r["sprites"]:
                w.writerow([r["oid"], r["level"], s["pack"], pack_label(s["pack"]), s["image"],
                            s["ox"], s["oy"], s["frames"], s["hide"], s["png"], int(s["drawable"])])


# ---------------------------------------------------------------- main
def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    tiles, objects, meta = load_sector()
    print(f"сектор: тайлов {len(tiles)}, объектов {len(objects)}")
    payload = build_elements(tiles, objects, meta)

    date = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    raw = OUT / "_sector_56_raw.png"
    rinfo = render_sector_png(tiles, objects, raw, max_side=3600)
    info = {
        "tiles": rinfo["tiles"],
        "counts_objects": payload["counts"]["objects"],
        "counts_sprites": payload["counts"]["sprites"],
        "width": rinfo["width"], "height": rinfo["height"],
        "scale": rinfo["scale"], "date": date,
    }
    frame_screenshot(raw, OUT / "sector_56_screenshot_hq.png", OUT / "sector_56_screenshot.jpg", info)
    raw.unlink(missing_ok=True)
    payload["render"] = {
        "fresh": {
            "scale": rinfo["scale"], "width": rinfo["width"], "height": rinfo["height"],
            "bbox": rinfo["bbox"], "tiles": rinfo["tiles"], "objects": rinfo["objects"],
            "files": ["sector_56_screenshot_hq.png", "sector_56_screenshot.jpg"],
        },
        "atlas_frame": {
            "file": "sector_56_atlas_1531x817.jpg",
            "source": "map_book/sectors/sector_x0700_y0400.jpg",
            "note": "готовая вырезка атласа, масштаб 1500/6432; там же кадр №16 диагонали",
            "caveat": (
                "в атласе объекты рисовались в порядке oid (без сортировки по depth), "
                "поэтому крыши/навесы местами перекрывают фасады; свежий рендер сортирует "
                "объекты по (level, depth, oid) и показывает сектор так, как его рисует приложение"
            ),
        },
    }

    if ATLAS_FRAME.is_file():
        shutil.copyfile(ATLAS_FRAME, OUT / "sector_56_atlas_1531x817.jpg")

    # JSON в формате самой программы («выгрузить JSON» для открытого сектора)
    app_jpg = OUT / "_app_render.jpg"
    export_region(X0, Y0, X1, Y1, OUT / "sector_56_app_export.json", app_jpg)
    app_jpg.unlink(missing_ok=True)

    n_packs = build_packs_sheet(objects, payload, OUT / "sector_56_packs.png")
    n_tiles = build_tiles_sheet(tiles, payload, OUT / "sector_56_tiles_palette.png")
    build_projection_diagram(OUT / "how_tiles_assemble.png")

    write_csvs(payload, OUT / "sector_56_tiles.csv", OUT / "sector_56_objects.csv",
               OUT / "sector_56_sprites.csv")
    payload["sprites_local"] = copy_sector_sprites(tiles, objects)

    out_json = OUT / "sector_56.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    payload["files"] = [
        {"name": f.name, "bytes": f.stat().st_size}
        for f in sorted(OUT.iterdir()) if f.is_file()
    ]
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    zip_path = BASE / "exports" / "Сектор_56_x700-799_y400-499.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(OUT.parent)))
    print(f"архив: {zip_path} ({zip_path.stat().st_size / 1e6:.2f} МБ)")

    print(f"готово за {time.time() - t0:.1f}s")
    print(f"  {out_json}  ({out_json.stat().st_size / 1e6:.2f} МБ)")
    print(f"  тайлов {payload['counts']['tiles']}, объектов {payload['counts']['objects']}, "
          f"спрайтов {payload['counts']['sprites']}")
    print("  земля:", payload["ground"]["by_category"])
    print("  объекты по категориям:", payload["objects_summary"]["by_category"])
    print("  объекты по этажам:", payload["objects_summary"]["by_level"])
    print("  топ-паки:", [(p["pack"], p["name"], p["sprites"]) for p in payload["objects_summary"]["packs"][:8]])
    print("  готовность:", payload["assembly_status"]["app_ready_hint"],
          "| стояний в секторе:", payload["assembly_status"]["stood_points_in_sector"])
    print(f"  паков на листе: {n_packs}, тайлов на листе: {n_tiles}")
    for f in sorted(OUT.iterdir()):
        print(f"   {f.name:36s} {f.stat().st_size / 1024:9.1f} КБ")


if __name__ == "__main__":
    main()
