# ===================== target_resolver.py 关键补丁开始 =====================
import os, math, json, cv2, time
from functools import lru_cache
from paddleocr import PaddleOCR
import config

# ---- 参数 ----
_OCR_RADIUS   = getattr(config, "OCR_NEAR_RADIUS_PX", 120)     # 点击点邻域半径
_YOLO_EXPAND  = getattr(config, "YOLO_EXPAND_RATIO", 0.15)     # YOLO 扩框 OCR
_OCR_THRES    = getattr(config, "OCR_CONFIDENCE", 0.6)         # 置信度阈值
_TEXT_MAXLEN  = getattr(config, "TARGET_TEXT_MAXLEN", 20)
_SSHOT_DIR    = getattr(config, "SCREENSHOT_PATH", "./screen/") # 截图目录

# ---- 懒加载 OCR：自动回退参数，兼容不同版本 ----
_OCR = None
def _get_ocr():
    global _OCR
    if _OCR is not None:
        return _OCR
    tries = [
        dict(use_angle_cls=True, lang='ch', det=True, rec=True, cls=True),   # 新版常用
        dict(use_angle_cls=True, lang='ch'),
        dict(),  # 兜底
    ]
    last_err = None
    for kw in tries:
        try:
            _OCR = PaddleOCR(**kw)
            print(f"[OCR] init with {kw}")
            return _OCR
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("PaddleOCR init failed")

# ---- 简单缓存 ----
_OCR_CACHE  = {}   # key: (img_path, x1,y1,x2,y2) -> [{"text","bbox","score"},...]
_YOLO_CACHE = {}   # key: sidx -> [{"bbox":[x1,y1,x2,y2],"label":"我的","score":0.9}, ...]

def _ensure_xyxy(box):
    x1, y1, x2, y2 = map(int, box)
    # 兼容 (x, y, w, h)
    if x2 <= x1 or y2 <= y1:
        x2 = x1 + max(0, x2)
        y2 = y1 + max(0, y2)
    return x1, y1, x2, y2

def _clip_xyxy(x1, y1, x2, y2, W, H):
    return max(0, x1), max(0, y1), min(W - 1, x2), min(H - 1, y2)

def _bbox_contains(x, y, box):
    if not box: return False
    x1, y1, x2, y2 = _ensure_xyxy(box)
    return (x1 <= x <= x2) and (y1 <= y <= y2)

def _expand(box, W, H, ratio):
    x1, y1, x2, y2 = _ensure_xyxy(box)
    w, h = x2 - x1, y2 - y1
    return [
        max(0, int(x1 - w * ratio)),
        max(0, int(y1 - h * ratio)),
        min(W - 1, int(x2 + w * ratio)),
        min(H - 1, int(y2 + h * ratio)),
    ]

def _roi(cx, cy, W, H, r):
    return [
        max(0, int(cx - r)), max(0, int(cy - r)),
        min(W - 1, int(cx + r)), min(H - 1, int(cy + r))
    ]

def _norm_text(s: str) -> str:
    s = ''.join(ch for ch in str(s) if '\u4e00' <= ch <= '\u9fff' or ch.isalnum())
    return (s[:_TEXT_MAXLEN] + '…') if len(s) > _TEXT_MAXLEN else s

def load_yolo_for_page(sidx):
    if sidx in _YOLO_CACHE:
        return _YOLO_CACHE[sidx]
    path = os.path.join(getattr(config, "PAGE_TEXT_PATH", "."), f"yolo_{sidx}.json")
    if os.path.exists(path):
        try:
            _YOLO_CACHE[sidx] = json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            _YOLO_CACHE[sidx] = []
    else:
        _YOLO_CACHE[sidx] = []
    return _YOLO_CACHE[sidx]

def _ocr_raw(img):
    ocr = _get_ocr()
    # 统一显式 det/rec/cls，让返回形态稳定些
    return ocr.ocr(img, det=True, rec=True, cls=True)

def _ocr(img, box, img_path=None):
    """对 box ROI 做 OCR，兼容新旧返回；带缓存。"""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = _ensure_xyxy(box)
    x1, y1, x2, y2 = _clip_xyxy(x1, y1, x2, y2, W, H)
    if (x2 - x1) <= 0 or (y2 - y1) <= 0:
        return []

    cache_key = (img_path or "mem", x1, y1, x2, y2)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]

    crop = img[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        _OCR_CACHE[cache_key] = []
        return []

    try:
        res = _ocr_raw(crop)
    except Exception:
        _OCR_CACHE[cache_key] = []
        return []

    out = []
    if not res:
        _OCR_CACHE[cache_key] = out
        return out

    # 新版字典结构
    if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict) and (
        ('rec_texts' in res[0]) or ('rec_polys' in res[0]) or ('rec_boxes' in res[0])
    ):
        d = res[0]
        texts  = d.get('rec_texts', []) or []
        scores = d.get('rec_scores', [1.0] * len(texts)) or []
        polys  = d.get('rec_polys') or d.get('det_polys')
        boxesA = d.get('rec_boxes')

        for i, txt in enumerate(texts):
            sc = float(scores[i]) if i < len(scores) else 1.0
            if sc < _OCR_THRES:
                continue
            if polys is not None and len(polys) > i:
                pts = polys[i]
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                bx = [min(xs) + x1, min(ys) + y1, max(xs) + x1, max(ys) + y1]
            elif boxesA is not None and len(boxesA) > i:
                xmin, ymin, xmax, ymax = boxesA[i]
                bx = [int(xmin) + x1, int(ymin) + y1, int(xmax) + x1, int(ymax) + y1]
            else:
                continue
            out.append({"text": _norm_text(txt), "score": sc, "bbox": list(map(int, bx))})
        _OCR_CACHE[cache_key] = out
        return out

    # 旧版 list/tuple 结构
    for lines in res:
        for entry in (lines or []):
            try:
                if not isinstance(entry, (list, tuple)) or len(entry) == 0:
                    continue
                pts = entry[0]
                if not isinstance(pts, (list, tuple)) or len(pts) < 4:
                    continue
                txt, sc = "", 0.0
                second = entry[1] if len(entry) >= 2 else None
                if isinstance(second, (list, tuple)) and len(second) >= 2 and not isinstance(second[0], (list, tuple, dict)):
                    txt = str(second[0]); sc = float(second[1])
                elif isinstance(second, dict):
                    txt = str(second.get("text", "")); sc = float(second.get("score", 0.0))
                if not txt or sc < _OCR_THRES:
                    continue

                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                bx = [min(xs) + x1, min(ys) + y1, max(xs) + x1, max(ys) + y1]
                out.append({"text": _norm_text(txt), "score": sc, "bbox": list(map(int, bx))})
            except Exception:
                continue

    _OCR_CACHE[cache_key] = out
    return out

def _nearest_text(ocr_items, x, y, max_r2):
    best = None
    for it in ocr_items:
        bx1, by1, bx2, by2 = it["bbox"]; cx = (bx1 + bx2) / 2; cy = (by1 + by2) / 2
        r2 = (cx - x)*(cx - x) + (cy - y)*(cy - y)
        if r2 > max_r2: 
            continue
        score = it["score"] / (1 + math.sqrt(r2))
        if (best is None) or score > best[0]:
            best = (score, it)
    return (best[1]["text"], best[1]["bbox"]) if best else ("", None)

def resolve_target_text_cached(sidx, x, y):
    """
    输入：截图 index、点击坐标
    输出：(target_text, target_bbox)
    策略：YOLO 命中优先（扩框 OCR），否则点击点邻域 OCR，二者都无 → ('', [x,y,0,0])
    """
    img_path = os.path.join(_SSHOT_DIR, f"{sidx}.png")
    img = cv2.imread(img_path)
    if img is None:
        return "", [int(x), int(y), 0, 0]
    H, W = img.shape[:2]

    # 1) YOLO 命中优先
    yolos = load_yolo_for_page(sidx)
    for it in yolos:
        box = it.get("bbox")
        if box and _bbox_contains(x, y, box):
            items = _ocr(img, _expand(box, W, H, _YOLO_EXPAND), img_path=img_path)
            txt, bb = _nearest_text(items, x, y, _OCR_RADIUS*_OCR_RADIUS)
            if not txt:
                # OCR 空 → 用 YOLO 的 label 兜底
                txt = _norm_text(it.get("label", ""))
                bb  = box
            if not bb:
                bb = [int(x), int(y), 0, 0]
            return txt, list(map(int, bb))

    # 2) 点击点邻域 OCR
    r = _OCR_RADIUS
    items = _ocr(img, _roi(x, y, W, H, r), img_path=img_path)
    txt, bb = _nearest_text(items, x, y, r*r)
    if not bb:
        bb = [int(x), int(y), 0, 0]
    return _norm_text(txt), list(map(int, bb))

__all__ = ["resolve_target_text_cached"]
# ===================== target_resolver.py 关键补丁结束 =====================
