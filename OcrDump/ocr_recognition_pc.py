# ===== 放在文件最顶部（第一行），任何 import 之前 =====
import time
import os, urllib.request

# 1) 干掉本进程的代理环境变量（大小写都覆盖）
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY","http_proxy","https_proxy","all_proxy","no_proxy","PROXY","proxy"):
    os.environ.pop(k, None)
# 显式声明不走任何代理
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# 2) 让 requests/urllib 忽略系统代理
try:
    import requests
    # 不从环境/系统继承代理配置
    requests.sessions.Session.trust_env = False
except Exception:
    pass

# urllib 默认会在 Windows 上读系统代理；这里强制返回空
urllib.request.getproxies = (lambda: {})

# 3)（可选但推荐）告诉 PaddleX/ PaddleOCR 走离线逻辑（即使没有也不影响）
os.environ["PADDLEX_OFFLINE"] = "1"
os.environ["PADDLEOCR_OFFLINE"] = "1"
# ===== 顶部补丁结束 =====

import hashlib
import string
import os
# for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
#     os.environ.pop(k, None)
# # 避免某些库自动抓系统代理
# os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1,huggingface.co,modelscope.cn,aistudio.baidu.com,paddle-model-ecology.bj.bcebos.com')

import sys
sys.path.append(r'G:\miniapp\XPOScope-main')

from paddleocr import PaddleOCR
# from dynamicExerciser import mini_app_utils_pc as miniAppUtils  # ★ PC 版
from dynamicExerciser import pc_commands as adb_commands        # ★ PC 版
import config
import cv2
import json
import os
import hashlib
# 只让本进程绕开系统/环境代理（WeChat 仍按系统代理走，不受影响）

# 建议显式参数，输出结构更稳定
# try:
#     # 先尝试新版本常用参数
#     ocr = PaddleOCR(use_angle_cls=False, lang='ch')
# except TypeError:
#     # 兜底：老版本默认构造
#     print("PaddleOCR: fallback to default constructor")
#     ocr = PaddleOCR()


# ocr = PaddleOCR(use_angle_cls=False, lang='ch',    det_db_box_thresh=0.2,     # 默认 0.6，调低更容易保留弱框
#     det_db_thresh=0.2,         # 二值化阈值，也稍降
#     det_db_unclip_ratio=2.0    # 稍微放大文本框，利于小字被覆盖
#     )


ocr = PaddleOCR(
    use_textline_orientation=False,            # 不进行方向分类（UI截图通常是正的，设为False能快很多）
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    lang='ch',
    ocr_version='PP-OCRv4',         # 强制使用 v4 轻量模型 (Mobile)
    # structure_version='PP-StructureV2', # 如果不需要表格识别，这项其实不重要
    # show_log=False,                 # 减少日志打印
    # use_gpu=False,                  # 明确使用 CPU
    enable_mkldnn=True,             # 【关键】开启 CPU 加速库
    
    # --- 修正过时的参数名 (根据你的报错日志) ---
    text_det_box_thresh=0.2,        # 替代 det_db_box_thresh
    text_det_thresh=0.2,            # 替代 det_db_thresh
    text_det_unclip_ratio=2.0,      # 替代 det_db_unclip_ratio
    text_recognition_batch_size=8,  # 替代 rec_batch_num
    
    cpu_threads=max(4, os.cpu_count() or 4)
)

# 2) OCR 缩图上限 & 结果缓存（按图内容 MD5 做缓存）
_OCR_MAX_SIDE = getattr(config, "OCR_MAX_SIDE", 1120)  # 你也可放到 config.py
_OCR_CACHE = {}  # key: md5(image_small bytes) -> result

def fill_target_text_from_ocr_file(page_idx, x, y, max_r=120):
    """从 ocr_{page_idx}.json 里找距 (x,y) 最近的一条"""
    import math
    # path = os.path.join(config.PAGE_TEXT_PATH, f"ocr_{page_idx}.json")
    path = os.path.join(config.PAGE_TEXT_PATH, f"ocr_raw_{page_idx}.json")
    try:
        items = json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return "", [int(x), int(y), 0, 0]

    best = None
    max_r2 = max_r * max_r
    for it in items:
        bx1, by1, bx2, by2 = it.get("bbox", [x,y,x,y])
        cx, cy = (bx1+bx2)/2.0, (by1+by2)/2.0
        r2 = (cx-x)*(cx-x) + (cy-y)*(cy-y)
        if r2 > max_r2:
            continue
        # 简单打分：越近越好 + 置信度越高越好
        score = it.get("score", 0.0) / (1.0 + math.sqrt(r2))
        if (best is None) or (score > best[0]):
            best = (score, it)

    if best is None:
        return "", [int(x), int(y), 0, 0]
    it = best[1]
    return it.get("text", ""), it.get("bbox", [int(x), int(y), 0, 0])


def cache_image_dump_str() -> [list, str, list]:
    # 可能需要进行临时截图（PC 版）
    adb_commands.adb_cache_screenshot()
    image_path = config.SCREENSHOT_CACHE_PATH + "temp.png"
    return dump_str(image_path, False)

import re, cv2, hashlib, string
# from dynamicExerciser import mini_app_utils_pc as miniAppUtils
import config

# 关键词：优先点击
_PRIORITY_RE = re.compile(r'(扫码|登录|确定|同意|允许|授权|开启定位|定位|手动|下一步|开始|设置|搜索|确认|同意|继续|隐私|客服|反馈)')
# 非按钮小字/地图点：尽量过滤
def _should_click(text, box, W, H):
    # 1) 单字符/纯数字，极可能无意义
    if text and (len(text) == 1 or text.isdigit()):
        # if not _PRIORITY_RE.search(text):
        return False
    # text为空
    if not text or text.strip() == '':
        return False
    # 2) 其它的放行（交由 BFS 尝试）
    return True
def _write_json(path, data):
    try:
        os.makedirs(config.PAGE_TEXT_PATH, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[OCR] write {os.path.basename(path)} failed: {e}")

def screenshot_dump_str(image_index, need_text_locations) -> [list, string, list]:
    image_path = config.SCREENSHOT_PATH + str(image_index) + ".png"
    return dump_str(image_path, need_text_locations)

import imagehash
from PIL import Image

_PROFILE = None
def get_profile():
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = load_profile(config.CONFIGS_PROFILE)
    return _PROFILE

def dump_str(image_path, need_text_locations, page_idx=None):
    
    import os, hashlib, cv2
    img = cv2.imread(image_path)
    if img is None:
        return [], hashlib.md5(b'').hexdigest(), []
    H, W = img.shape[:2]
    t1= time.time()
    # ---------- 可选：全图放大兜底（小字更容易被检出） ----------
    global_scale = float(getattr(config, "OCR_GLOBAL_SCALE", 0.0) or 0.0)
    if global_scale and abs(global_scale - 1.0) > 1e-3:
        img_big = cv2.resize(img, None, fx=global_scale, fy=global_scale, interpolation=cv2.INTER_CUBIC)
        res_full = ocr.ocr(img_big)
        scale_full = global_scale
        def _map_back(x, y):  # 放大坐标映射回原图
            return x/scale_full, y/scale_full
    else:
        res_full = ocr.ocr(img)
        scale_full = 1.0
        def _map_back(x, y):
            return x, y
    t2= time.time()
    # print("OCR full image result:")
    # print(res_full)

    res_dump_str, ocr_click_locations = [], []
    raw_hits, click_hits = [], []
    

    def _push_hits(xmin, ymin, xmax, ymax, txt):
        # 统一入 raw_hits
        cx, cy = int((xmin+xmax)/2), int((ymin+ymax)/2)
        # 用你现有的业务过滤（如需更松，把 _should_click 放宽或去掉）
        if not _should_click(txt, (xmin,ymin,xmax,ymax), W, H):
            return
        click_hits.append({
            "text": remove_symbols(txt),
            "bbox": [int(xmin), int(ymin), int(xmax), int(ymax)],
            "click_xy": [cx, cy]
        })

    # ---------- 解析 PaddleOCR 输出的一个小工具 ----------
    def _consume_paddle_out(res_any, map_back):
        out = []
        # 新版 dict 结构
        if isinstance(res_any, list) and len(res_any) > 0 and isinstance(res_any[0], dict) and 'rec_texts' in res_any[0]:
            d = res_any[0]
            texts  = d.get('rec_texts', [])
            polys  = d.get('rec_polys', None)
            boxesA = d.get('rec_boxes', None)
            for i, txt in enumerate(texts):
                if polys is not None and len(polys) > i:
                    pts = polys[i]; x1,y1 = pts[0]; x3,y3 = pts[2]
                    xmin,ymin = map_back(min(x1,x3), min(y1,y3))
                    xmax,ymax = map_back(max(x1,x3), max(y1,y3))
                    out.append((xmin,ymin,xmax,ymax,txt))
                elif boxesA is not None and len(boxesA) > i:
                    x1,y1,x2,y2 = boxesA[i]
                    xmin,ymin = map_back(x1,y1)
                    xmax,ymax = map_back(x2,y2)
                    out.append((xmin,ymin,xmax,ymax,txt))
        else:
            # 旧版 list 结构
            for lines in (res_any or []):
                for line in lines:
                    try:
                        pts = line[0]
                        txt = line[1][0]
                        x1,y1 = pts[0]; x3,y3 = pts[2]
                        xmin,ymin = map_back(min(x1,x3), min(y1,y3))
                        xmax,ymax = map_back(max(x1,x3), max(y1,y3))
                        out.append((xmin,ymin,xmax,ymax,txt))
                    except Exception:
                        continue
        return out

    # ---------- A 通道：全图 OCR ----------
    for (xmin,ymin,xmax,ymax,txt) in _consume_paddle_out(res_full, _map_back):
        _push_hits(xmin, ymin, xmax, ymax, txt)
        cx, cy = int((xmin+xmax)/2), int((ymin+ymax)/2)
        res_dump_str.append(remove_symbols(txt))
        if need_text_locations:
            ocr_click_locations.append([cx, cy])

    # ---------- B 通道：底部 ROI 放大二次 OCR（关键！） ----------
    bottom_ratio = float(getattr(config, "OCR_BOTTOM_RATIO", 0.12) or 0.12)
    bottom_scale = float(getattr(config, "OCR_BOTTOM_SCALE", 2.0) or 2.0)
    y0 = int(H * (1.0 - bottom_ratio))
    y1 = H
    roi = img[y0:y1, 0:W]
    if roi is not None and roi.size > 0:
        roi_big = cv2.resize(roi, None, fx=bottom_scale, fy=bottom_scale, interpolation=cv2.INTER_CUBIC)
        res_bottom = ocr.ocr(roi_big)
        def _map_back_bottom(x, y):
            # 先从放大 ROI 映回原 ROI，再叠加 y0
            return x/bottom_scale, y/bottom_scale + y0
        for (xmin,ymin,xmax,ymax,txt) in _consume_paddle_out(res_bottom, _map_back_bottom):
            _push_hits(xmin, ymin, xmax, ymax, txt)
            cx, cy = int((xmin+xmax)/2), int((ymin+ymax)/2)
            res_dump_str.append(remove_symbols(txt))
            if need_text_locations:
                ocr_click_locations.append([cx, cy])

    t3= time.time()
    # ---------- 生成最终用于 BFS 的点击点 ----------
    budget= config.OCR_CLICK_BUDGET
#     # 2) 新版本：关键词排序 + budget 截断（你可以在 config 里放关键词表）


    profile = get_profile()

    strong_kw = profile["OCR_STRONG_KEYWORDS"]
    tab_kw    = profile["OCR_TAB_KEYWORDS"]
    weak_kw   = profile["OCR_WEAK_KEYWORDS"]
    quota_strong = profile["OCR_QUOTA_STRONG"]
    quota_tab    = profile["OCR_QUOTA_TAB"]
    quota_weak  = profile["OCR_QUOTA_WEAK"]

    def _prio(hit): 
        x, y = hit["click_xy"] 
        text = hit["text"] 
        s = 0.0 # 位置：底部略加分（但不做二次 OCR） 
        if y > 0.88 * H: s += 1.0 # 强关键词优先 
        if any(k in text for k in strong_kw): s += 3.0 
        if any(k in text for k in tab_kw): s += 2.0 # 弱词降权 
        if any(k in text for k in weak_kw): s += 1.5 # bbox 面积过小降权（避免地图小字/噪声） 
        return s
    def _is_any(text, kws): 
        return any(k in text for k in kws)
    
    strong_hits, tab_hits, other_hits, weak_hits = [], [], [], []
    for h in click_hits:
        text = h["text"]
        if _is_any(text, strong_kw):
            strong_hits.append(h)
        elif _is_any(text, tab_kw):
            tab_hits.append(h)
        elif _is_any(text, weak_kw):
            weak_hits.append(h)
        else:
            other_hits.append(h)

    # 桶内排序：仍然用你的 _prio 或简单用 y/面积等
    def _prio_cached(hit):
        return hit.get("score", 0.0)

    # 先把 score 算好（避免桶内重复计算）
    for h in click_hits:
        h["score"] = float(_prio(h))

    strong_hits.sort(key=_prio_cached, reverse=True)
    tab_hits.sort(key=_prio_cached, reverse=True)
    # other_hits.sort(key=_prio_cached, reverse=True)
    weak_hits.sort(key=_prio_cached, reverse=True)

    picked = []
    def _take(lst, k):
        for h in lst:
            if len(picked) >= budget: 
                break
            # xy = tuple(h["click_xy"])
            text = h["text"]
            # 去重（同点不重复）
            if any(p["text"] == text for p in picked):
                continue
            picked.append(h)
            # print(f"[OCR] pick: text='{h['text']}' score={h['score']} at {h['click_xy']}")
            if k is not None:
                k -= 1
                if k <= 0:
                    break

    _take(strong_hits, quota_strong)
    _take(tab_hits, quota_tab)
    _take(weak_hits, quota_weak)

    # 不足 budget 再用 weak/剩余补齐
    if len(picked) < budget:
        _take(weak_hits, None)


    click_hits_sorted = picked
    ocr_click_locations = [h["click_xy"] for h in click_hits_sorted[:budget]]

    t4= time.time()
    print(f"[OCR] dump_str  OCR time: res_full  {t2 - t1:.2f}s, res_bottom  {t3 - t2:.2f}s, hits {len(ocr_click_locations)}")
    print(f"[OCR] dump_str  ocr+rule  time: {t4 - t3:.2f}s")
    # 写盘：raw 全量、click 可点击 
    if page_idx is None:
        try:
            base = os.path.basename(image_path)
            page_idx = int(os.path.splitext(base)[0])
        except Exception:
            page_idx = "temp"
    # _write_json(os.path.join(config.PAGE_TEXT_PATH, f"ocr_raw_{page_idx}.json"), raw_hits)
    _write_json(os.path.join(config.PAGE_TEXT_PATH, f"ocr_raw_{page_idx}.json"),      click_hits)
    _write_json(os.path.join(config.PAGE_TEXT_PATH, f"ocr_sorted_{page_idx}.json"),      click_hits_sorted)
    # print("click_hits_sorted", click_hits_sorted)
    md5 = hashlib.md5(''.join(res_dump_str).encode('utf-8')).hexdigest()


    # 【修改点】：直接读取原图计算真实的感知哈希 (pHash)
    try:
        # image_path 是 dump_str 传进来的原图路径
        phash_val = str(imagehash.phash(Image.open(image_path)))
    except Exception:
        # 兜底：如果读取失败，返回一个空哈希
        phash_val = "0000000000000000"
    conf_th = float(getattr(config, "OCR_CONFIDENCE", 0.0) or 0.0)  # 你已放宽阈值，这里默认不过滤


    res_dump_str2=[h["text"] for h in click_hits_sorted[:budget]]
    # return res_dump_str, phash_val, ocr_click_locations
    return res_dump_str, md5, ocr_click_locations


import json
import os

def load_profile(profile_path: str) -> dict:
    """
    读取 json profile，失败则返回空 dict
    """
    if not profile_path:
        return {}
    try:
        if not os.path.isabs(profile_path):
            profile_path = os.path.abspath(profile_path)
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def getv(profile: dict, key: str, default):
    """
    profile 优先，其次 default
    """
    v = profile.get(key, None) if isinstance(profile, dict) else None
    return default if v is None else v


def remove_symbols(target_str):
    res_str = ''
    for char in target_str:
        if '\u4e00' <= char <= '\u9fa5' or char in string.digits or char in string.ascii_letters:
            res_str += char
    return res_str

def remove_keyboard(current_dump_str: list) -> list:
    res = []
    license_plate = '省京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽赣粤青藏川宁琼使领警学港澳贵'
    for dump_str in current_dump_str:
        if not (len(dump_str) == 1 and dump_str in string.ascii_letters + string.punctuation + license_plate):
            res.append(dump_str)
    return res


_BACK_RE = re.compile(r'(返回|上一步|关闭|取消|完成|我知道了|同意|允许|继续|Back|Cancel|Close|OK|Done)')

def try_ocr_back_click() -> bool:
    """
    在屏幕上方 30% 高度范围内 OCR，命中关键词即点击其 bbox 中心。
    返回 True=点击了一个候选；False=没命中。
    """
    temp = "temp"
    adb_commands.adb_screenshot(temp)
    img_path = os.path.join(config.SCREENSHOT_PATH, f"{temp}.png")
    img = cv2.imread(img_path)
    if img is None: 
        return False
    H, W = img.shape[:2]
    # 仅截上方区域加速&降噪
    roi = img[0:int(0.30*H), 0:W].copy()

    hits = []  # [(score, cx, cy, text)]
    try:
        res = ocr.ocr(roi)  # 你现有的 PaddleOCR 实例
        conf_th = getattr(config, "OCR_CONFIDENCE", 0.6)
        if res:
            # 兼容两种返回结构
            if isinstance(res, list) and len(res)>0 and isinstance(res[0], dict) and 'rec_texts' in res[0]:
                d = res[0]
                texts  = d.get('rec_texts', [])
                # scores = d.get('rec_scores', [1.0]*len(texts))
                polys  = d.get('rec_polys', None)
                boxesA = d.get('rec_boxes', None)
                for i, txt in enumerate(texts):
                    # sc = float(scores[i]) if i<len(scores) else 1.0
                    # if sc < conf_th: 
                    #     continue
                    if not _BACK_RE.search(txt or ''):
                        continue
                    if polys is not None and i < len(polys):
                        pts = polys[i]; x1,y1 = pts[0]; x3,y3 = pts[2]
                        xmin,ymin,xmax,ymax = min(x1,x3),min(y1,y3),max(x1,x3),max(y1,y3)
                    elif boxesA is not None and i < len(boxesA):
                        xmin,ymin,xmax,ymax = boxesA[i]
                    else:
                        continue
                    cx, cy = int((xmin+xmax)/2), int((ymin+ymax)/2)
                    # ROI 相对 → 全图坐标
                    cy += 0
                    # hits.append((sc, cx, cy, txt))
                    hits.append(( cx, cy, txt))
            else:
                for lines in res:
                    for line in lines:
                        try:
                            pts = line[0]
                            # txt, sc = line[1][0], float(line[1][1])
                            txt= line[1][0]
                        except Exception:
                            continue
                        # if sc < conf_th or not _BACK_RE.search(txt or ''):
                        #     continue
                        x1,y1 = pts[0]; x3,y3 = pts[2]
                        xmin,ymin,xmax,ymax = min(x1,x3),min(y1,y3),max(x1,x3),max(y1,y3)
                        cx, cy = int((xmin+xmax)/2), int((ymin+ymax)/2)
                        # hits.append((sc, cx, cy, txt))
                        hits.append(( cx, cy, txt))
    except Exception:
        return False

    if not hits:
        return False

    # 选最高分
    hits.sort(key=lambda t: t[0], reverse=True)
    _, cx, cy, txt = hits[0]
    adb_commands.adb_click(cx, cy)  # 用你现有的坐标映射
    return True
