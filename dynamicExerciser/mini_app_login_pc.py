import time
import json
import traceback
from typing import Optional, Tuple

from pywinauto import Desktop, Application
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.base_wrapper import BaseWrapper

from pywinauto import Application, Desktop
import time
path="G:\miniapp\code\mitmsession\\"
import csv, time, os

# 小工具：把当前窗口能看到的文字抓一份（作为“页面意图证据”）
def collect_all_visible_texts(win):
    texts = []
    for c in win.descendants():
        try:
            if c.is_visible():
                t = (c.window_text() or "").strip()
                if t:
                    texts.append(t)
        except Exception:
            pass
    return texts

# 小工具：把 UI 事件写到 CSV（时间戳 / 动作 / 页面提示 / 前后可见文本）
import csv, time, os
UI_LOG = "ui_events.csv"

def log_ui_event(action, page_hint, win):
    os.makedirs(os.path.dirname(UI_LOG) or ".", exist_ok=True)
    with open(UI_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            int(time.time()*1000),
            action,
            page_hint,
            " ".join(collect_all_visible_texts(win))[:2000]
        ])

# 用法（你点击前/后都可以写）：
# log_ui_event("click:我的", "tabbar:mine", collect_all_visible_texts(mini_win))


# 从文件读取小程序列表
def read_program_list(file_path):
    with open(path+file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]
    
def run_automation_test(program_name):
    """运行自动化测试（pywinauto）"""
    windows = Desktop(backend="uia").windows()
    print("run_automation_test")
    print(f"总共找到 {len(windows)} 个窗口:")

    PID = None
    for w in windows:
        try:
            title = w.window_text()
            pid = w.process_id()
            cls = w.friendly_class_name()
            if cls == 'Pane' and title == '微信':
                PID = pid
                break
        except Exception as e:
            print("无法读取窗口信息:", e)

    if not PID:
        print("未找到微信窗口，请确保微信已打开")
        return
    app = Application(backend="uia").connect(process=PID)
    win_spec = app.window(title="微信")
    win_spec.set_focus()
    print(win_spec.rectangle())

    rect = win_spec.rectangle()
    abs_x = (rect.left + rect.right) // 2
    abs_y = (rect.top + rect.bottom) // 2
    # rel_x = abs_x - rect.left + 310
    # rel_y = abs_y - rect.top - 380
    rel_x = abs_x - rect.left + 380
    rel_y = abs_y - rect.top - 395

    print(f"正在处理小程序: {program_name}")
    # 点击搜索框
    win_spec.click_input(coords=(rel_x, rel_y))
    # 输入名称
    win_spec.type_keys(program_name, with_spaces=True)
    win_spec.type_keys("{ENTER}")
    time.sleep(3)
    # 点击第一个结果
    x = abs_x - rect.left - 250
    y = abs_y - rect.top - 300
    win_spec.click_input(coords=(x, y))
    print("✅ 已点击，尝试打开小程序！")
    time.sleep(3)

    try:
        mini_win = Desktop(backend="uia").window(title_re=f".*{program_name}.*")
        if mini_win.exists():
            mini_win.set_focus()
            # time.sleep(30)  
            # mini_win.close()
            # time.sleep(2)
            
            return mini_win
            # return 
        else:
            print(f"❌ 未找到小程序窗口: {program_name}")
    except Exception as e:
        print(f"处理小程序窗口时出错: {e}")
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import json, os, time, argparse, re
from typing import List, Tuple, Optional, Dict, Any
from pywinauto.base_wrapper import BaseWrapper


def _center_y(rect):
    l, t, r, b = rect
    return (t + b) / 2.0

def _is_bottom_roi(win_rect, rect, bottom_ratio: float) -> bool:
    """rect 的中心是否落在窗口底部 bottom_ratio 高度的区域内"""
    H = win_rect.height()
    return _center_y(rect) >= (win_rect.bottom - H * bottom_ratio)

def click_bottom_profile_tab(mini_win: BaseWrapper,
                             keywords: List[str],
                             bottom_ratio: float = 0.32,
                             max_text_len: int = 6,
                             topk: int = 8,
                             click_timeout: float = 4.5) -> int:
    """
    只在窗口底部 ROI 内寻找 “我的/个人/我/账号/资料/设置” 等**短文案**，用于命中 TabBar。
    命中后点击并等待常规哨兵（在外部再判定）。
    """
    if not mini_win or not mini_win.exists():
        return 0

    W = mini_win.rectangle()
    controls = _collect_text_controls(mini_win)
    # print("controls")
    # print(controls)

    cands = []
    for c in controls:
        name = _text(c)
        if not name:
            continue
        # 关键词 + 短文案（避免整段页面文案）
        if not any(k in name for k in keywords):
            continue
        if len(name.strip()) > max_text_len:
            continue
        rect = _rect(c)
        # 只看底部 ROI
        if not _is_bottom_roi(W, rect, bottom_ratio):
            continue
        # 小区域优先（避免整块容器）
        l, t, r, b = rect
        area = (r - l) * (b - t)
        area_penalty = min(1.0, area / 60000.0)
        # 典型“Button/Static”稍微加分
        cls = _class_name(c).lower()
        type_bonus = 0.8 if "button" in cls else (0.5 if ("text" in cls or "static" in cls) else 0.3)
        # 越靠底越好
        bottomness = max(0.0, min(1.0, (W.bottom - _center_y(rect)) / float(max(1, W.height()))))
        score = 2.0 * bottomness + 1.5 * type_bonus - 0.6 * area_penalty
        cands.append((score, c, name, rect))

    if not cands:
        # print("error1")
        return 0

    cands.sort(key=lambda x: x[0], reverse=True)
    print("[PROFILE-TAB] ROI candidates:")
    for i, (s, c, name, (l, t, r, b)) in enumerate(cands[:topk], 1):
        print(f"  {i:02d}. score={s:.2f} '{name}' rect=({l},{t},{r},{b}) cls={_class_name(c)}")

    for rank, (s, c, name, rect) in enumerate(cands[:topk], 1):
        print(f"[PROFILE-TAB] try #{rank}: '{name}'")
        if _ascend_click(mini_win, c):
            # 给页面一点时间变化；真正的“到位”由外层哨兵判断
            log_ui_event(f"clicked:{c}", "profile_candidate", mini_win)
            ok = _wait_for_sentinels(mini_win,
                                     ["个人信息", "手机号", "绑定", "账号", "帐户", "登录"],
                                     timeout=click_timeout)
            if ok:
                print("[PROFILE-TAB] 命中哨兵 -> 成功")
                return 1
            else:
                print("[PROFILE-TAB] 未命中哨兵，可能已经成功登录。将交由上层继续策略")
                return 2   # 让上层继续用通用 Step1 或做 back 后重试
    return 2

def safe_back(mini_win: BaseWrapper) -> bool:
    """
    通用回退：优先找“返回/关闭/取消”，找不到就点窗口内**左上角**的常见返回区域。
    """
    if not mini_win or not mini_win.exists():
        return False

    # A) 文本回退
    for word in ["返回", "取消", "完成", "收起", "Done", "Back"]:
        for c in mini_win.descendants():
            if not _visible(c):
                continue
            if word in (_text(c) or ""):
                print(f"[BACK] click text node '{word}'")
                if _ascend_click(mini_win, c):
                    time.sleep(0.4)
                    return True

    # B) 近左上的无文案按钮/图标
    WR = mini_win.rectangle()
    hits = []
    for c in mini_win.descendants():
        if not _visible(c):
            continue
        l, t, r, b = _rect(c)
        # 在窗口内 左上 120x120 的区域内，小尺寸
        if l - WR.left > 140 or t - WR.top > 140:
            continue
        w, h = r - l, b - t
        if w <= 8 or h <= 8 or w > 80 or h > 80:
            continue
        cls = _class_name(c).lower()
        if "button" in cls or "pane" in cls or "image" in cls:
            hits.append((w*h, c))
    if hits:
        hits.sort(key=lambda x: x[0])  # 小的更像返回箭头
        c = hits[0][1]
        print(f"[BACK] click top-left control cls={_class_name(c)} rect={_rect(c)}")
        if _ascend_click(mini_win, c):
            time.sleep(0.4)
            return True

    # C) 兜底：窗口内固定偏移（一般能点到返回箭头）
    try:
        x_rel, y_rel = 25, 38
        print(f"[BACK] fallback click ({x_rel},{y_rel})")
        mini_win.click_input(coords=(x_rel, y_rel))
        time.sleep(0.4)
        return True
    except Exception:
        return False



# =========================
# 配置（可被 --config 覆盖）
# =========================
DEFAULT_CFG = {
    # 第一步：去“我的/个人/信息”页
    "step_profile": {
        "keywords": ["我的", "个人", "个人中心", "我", "个人信息", "信息", "账号", "帐户", "资料", "设置"],
        "sentinels": ["个人信息", "手机号", "手机验证", "验证码", "昵称", "绑定", "账号", "帐户", "登录"]
    },
    # 第二步：点击登录入口
    "step_login_entry": {
        "keywords": ["授权登录", "登录", "立即登录", "账号登录", "帐号登录", "手机号登录", "短信登录", "验证码登录", "微信登录"],
        "sentinels": ["手机号", "验证码", "短信", "密码", "一键登录", "本机号码", "同意并继续", "授权"]
    },
    # 第三步：一键登录类按钮
    "step_onetap": {
        "keywords": ["一键登录","一键授权登录","允许", "手机号快捷登录","本机号码一键登录", "一键绑定", "本机号码验证", "本机号码一键绑定", "同意并继续"],
        "sentinels": ["已登录", "退出登录", "绑定成功", "已绑定", "欢迎", "我的订单", "个人信息","尾号"]
    },
    # 全局隐私/授权处理（按钮/复选框）
    "global_consent": {
        # 识别“弹窗”按钮（正向/负向）
        "agree_words": ["同意", "允许", "确认", "知道了", "我知道了", "我已知晓", "继续", "接受", "同意并继续", "确认授权", "去使用", "OK"],
        "negative_words": ["拒绝", "不同意", "不允许", "取消", "暂不", "稍后", "关闭", "否"],
        # 识别“同意文本”行（用于找左侧复选圈）
        "consent_text_words": ["已阅读并同意", "我已阅读并同意", "隐私政策", "隐私协议", "个人信息保护", "用户协议", "服务协议", "个人信息保护政策"],
        # 偏移点击（当找不到小控件时，以“文本左边缘 ← offset_px”兜底）
        "checkbox_left_offset_px": 22,
        # 新增：勾完同意后，优先点击这些“主按钮”
        "primary_cta_words": ["手机号快捷登录", "一键登录", "同意并继续", "确认并继续", "本机号码一键登录", "立即登录", "去登录", "授权登录", "继续使用", "开始使用"],
        # 新增：对话框点击器里，不要把这些“文案行”当按钮
        "dialog_exclude_words": ["已阅读并同意", "隐私", "协议", "政策", "用户协议", "个人信息"]
    },
    
    # 通用参数
    "general": {
        "topk": 10,
        "try_k": 8,
        "click_timeout": 6.0,
        "guard_rounds": 3         # 每次进入守门员最多尝试轮数
    },
    # 在 DEFAULT_CFG["step_profile"] 增补
    "roi_bottom_ratio": 0.32,
    "max_text_len": 6
}

# =========================
# 基础工具（与你原算法一致）
# =========================
def _rect(w: BaseWrapper):
    r = w.rectangle()
    return r.left, r.top, r.right, r.bottom

def _visible(w: BaseWrapper) -> bool:
    try:
        r = w.rectangle()
        return r.width() > 2 and r.height() > 2 and w.is_visible()
    except Exception:
        return False

def _text(w: BaseWrapper) -> str:
    try:
        return (w.window_text() or "").strip()
    except Exception:
        return ""

def _class_name(w: BaseWrapper) -> str:
    try:
        return w.friendly_class_name()
    except Exception:
        return ""

def _score_candidate(win_rect, w: BaseWrapper, name: str, target_words: List[str]) -> float:
    L, T, R, B = win_rect.left, win_rect.top, win_rect.right, win_rect.bottom
    wl, wt, wr, wb = _rect(w)
    w_h = B - T
    bottomness = max(0.0, min(1.0, (B - (wt + (wb - wt) / 2)) / float(max(1, w_h))))
    cls = _class_name(w).lower()
    type_bonus = 0.0
    if "button" in cls: type_bonus = 1.0
    elif "pane" in cls: type_bonus = 0.6
    elif "text" in cls or "static" in cls: type_bonus = 0.4
    kw = 0.0
    for i, word in enumerate(target_words):
        if word in name:
            kw = max(kw, 2.0 + (len(target_words) - i) * 0.02)
    area = (wr - wl) * (wb - wt)
    area_bonus = min(1.0, area / 40000.0)
    return kw * 2.0 + bottomness * 1.2 + type_bonus * 1.0 + area_bonus * 0.3

def _ascend_click(win: BaseWrapper, w: BaseWrapper) -> bool:
    win.set_focus()
    tried = set()
    cur = w
    for _ in range(6):
        try:
            if cur in tried:
                break
            tried.add(cur)
            cur.click_input()
            # print("test")
            # print(cur)
            log_ui_event(f"clicked:{cur}", "profile_candidate", mini_win)
            return True
        except Exception:
            try:
                cur = cur.parent()
            except Exception:
                break
    try:
        wl, wt, wr, wb = _rect(w)
        WR = win.rectangle()
        cx = int((wl + wr) / 2 - WR.left)
        cy = int((wt + wb) / 2 - WR.top)
        win.click_input(coords=(cx, cy))
        return True
    except Exception:
        return False

def _collect_text_controls(win: BaseWrapper) -> List[BaseWrapper]:
    out = []
    for c in win.descendants():
        if not _visible(c): 
            continue
        name = _text(c)
        if not name:
            continue
        out.append(c)
    return out

def _wait_for_sentinels(win: BaseWrapper, sentinels: List[str], timeout: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        texts = []
        for c in win.descendants():
            nm = _text(c)
            if nm:
                texts.append(nm)
        joined = " ".join(texts)
        if any(s in joined for s in sentinels):
            return True
        time.sleep(0.3)
    return False

# =========================
# 通用“找字→点击→等哨兵”
# =========================
def click_by_keywords(mini_win: BaseWrapper,
                      keywords: List[str],
                      sentinels: List[str],
                      topk: int = 10,
                      try_k: int = 8,
                      click_timeout: float = 6.0,
                      step_name: str = "") -> int:
    if not mini_win or not mini_win.exists():
        print(f"[{step_name}] mini_win 不可用")
        return 0

    W = mini_win.rectangle()
    controls = _collect_text_controls(mini_win)

    scored: List[Tuple[float, BaseWrapper, str]] = []
    for c in controls:
        name = _text(c)
        if not any(word in name for word in keywords):
            continue
        s = _score_candidate(W, c, name, keywords)
        scored.append((s, c, name))

    if not scored:
        print(f"[{step_name}] 未找到包含关键词的控件：{keywords}")
        return 0

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"[{step_name}] 候选 Top{min(topk, len(scored))}：")
    for i, (s, c, name) in enumerate(scored[:topk], 1):
        wl, wt, wr, wb = _rect(c)
        print(f"  {i:02d}. score={s:.2f}  '{name}'  rect=({wl},{wt},{wr},{wb})  cls={_class_name(c)}")

    for rank, (s, c, name) in enumerate(scored[:try_k], 1):
        print(f"[{step_name}] 尝试点击#{rank}: '{name}' (score={s:.2f})")
        ok = _ascend_click(mini_win, c)
        if not ok:
            print(f"[{step_name}] 点击失败，换下一个候选")
            continue
        log_ui_event(f"clicked:{c}", "profile_candidate", mini_win)
        hit = _wait_for_sentinels(mini_win, sentinels, timeout=click_timeout)
        if hit:
            print(f"[{step_name}] 命中哨兵 -> 成功")
            return 1
        else:
            print(f"[{step_name}] 未观察到哨兵，继续尝试其他候选…")
    print(f"[{step_name}] 失败：在前{try_k}个候选内未命中哨兵。可能已登录成功！")
    return 0

# =========================
# 全局隐私/授权“守门员”
#   A) 文本左侧“复选圈”  B) 弹窗“同意/允许/知道了”等按钮
# =========================
def _click_point(win: BaseWrapper, x_rel: int, y_rel: int) -> bool:
    try:
        win.set_focus()
        win.click_input(coords=(x_rel, y_rel))
        
        return True
    except Exception:
        return False

def _find_text_nodes_for_consent(win: BaseWrapper, words: List[str]) -> List[BaseWrapper]:
    """过滤掉超大容器/Document，只保留像“已阅读并同意 …”那样的文本节点"""
    nodes = []
    WR = win.rectangle()
    wW, wH = WR.width(), WR.height()
    max_area = wW * wH * 0.35
    for c in win.descendants():
        if not _visible(c): 
            continue
        cls = _class_name(c).lower()
        if cls == "document":
            continue
        nm = _text(c)
        if not nm or not any(k in nm for k in words):
            continue
        l, t, r, b = _rect(c)
        area = max(1, (r - l) * (b - t))
        if area > max_area:
            continue
        nodes.append(c)
    return nodes

def _find_checkbox_near_text(win: BaseWrapper, text_node: BaseWrapper) -> Optional[BaseWrapper]:
    try:
        tl, tt, tr, tb = _rect(text_node)
        parent = text_node.parent()
    except Exception:
        parent = None
    if not parent: 
        return None
    t_mid = (tt + tb) // 2
    best = None
    for ch in parent.children():
        if ch is text_node or not _visible(ch):
            continue
        cl, ct, cr, cb = _rect(ch)
        w, h = (cr - cl), (cb - ct)
        left_of = cr <= tl + 6
        vertical_overlap = not (cb < tt or ct > tb)
        smallish = (w <= 48 and h <= 48)
        if left_of and vertical_overlap and smallish:
            cls = _class_name(ch).lower()
            kind = 1.0 if "checkbox" in cls else (0.7 if "button" in cls or "pane" in cls else 0.4)
            dist = abs(t_mid - (ct + h // 2)) + abs(tl - cr)
            score2 = kind + max(0, 160 - dist) / 160.0
            best = (score2, ch, (cl, ct, cr, cb))
    if best:
        return best[1]
    return None

def auto_consent_checkbox(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
    gw = cfg["global_consent"]
    WR = mini_win.rectangle()
    wW, wH = WR.width(), WR.height()

    cands = []
    for n in _find_text_nodes_for_consent(mini_win, gw["consent_text_words"]):
        l, t, r, b = _rect(n)
        h, w = (b - t), (r - l)
        area = max(1, w * h)
        txt = _text(n)
        bottomness = (WR.bottom - (t + h / 2.0)) / max(1.0, float(wH))
        height_ok = 1.0 if h <= 160 else 0.3
        len_penalty = 0.0 if 4 <= len(txt) <= 80 else 0.6
        area_penalty = min(1.0, area / float(wW * wH * 0.25))
        score = 3.0 * bottomness + 1.2 * height_ok - 1.0 * len_penalty - 1.0 * area_penalty
        cands.append((score, n, txt, (l, t, r, b)))
    if not cands:
        return False

    cands.sort(key=lambda x: x[0], reverse=True)
    _, target, txt, (tl, tt, tr, tb) = cands[0]
    print(f"[CONSENT-CB] target text: '{txt[:40]}' rect=({tl},{tt},{tr},{tb})")
    
    cb_node = _find_checkbox_near_text(mini_win, target)
    if cb_node:
        cl, ct, cr, cb = _rect(cb_node)
        print(f"[CONSENT-CB] 左侧小控件 rect=({cl},{ct},{cr},{cb}) -> click")
        log_ui_event(f"click:左侧小控件", "profile_candidate", mini_win)
        return _ascend_click(mini_win, cb_node)

    # 偏移兜底（相对窗口坐标）
    offset = int(gw.get("checkbox_left_offset_px", 22))
    x_rel = max(10, min(wW - 10, (tl - WR.left) - offset))
    y_rel = max(10, min(wH - 10, int((tt + tb) / 2) - WR.top))
    print(f"[CONSENT-CB] 偏移点击 -> (x={x_rel}, y={y_rel})")
    log_ui_event(f"clicked:offset", "profile_candidate", mini_win)
    return _click_point(mini_win, x_rel, y_rel)

def _is_negative_text(name: str, negatives: List[str]) -> bool:
    if not name:
        return False
    if any(n in name for n in negatives):
        return True
    # “不…同意”/“不…允许”之类
    if re.search(r"不.*(同意|允许)", name):
        return True
    return False

# def auto_consent_dialog(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
#     """点击弹窗中的“同意/允许/确认/继续/知道了/接受”等按钮（避开负向）"""
#     gw = cfg["global_consent"]
#     agree = gw["agree_words"]; neg = gw["negative_words"]

#     W = mini_win.rectangle()
#     cx_win = (W.left + W.right) / 2.0
#     cy_win = (W.top + W.bottom) / 2.0
#     diag = max(1.0, ((W.right - W.left)**2 + (W.bottom - W.top)**2) ** 0.5)

#     best = None
#     for c in mini_win.descendants():
#         if not _visible(c):
#             continue
#         name = _text(c)
#         if not name:
#             continue
#         if not any(w in name for w in agree):
#             continue
#         if _is_negative_text(name, neg):
#             continue
#         l, t, r, b = _rect(c)
#         x_mid, y_mid = (l + r) / 2.0, (t + b) / 2.0
#         center_bonus = 1.0 - min(1.0, (((x_mid - cx_win)**2 + (y_mid - cy_win)**2) ** 0.5) / diag)  # 越靠中心越高
#         size_bonus = min(1.0, ((r - l) * (b - t)) / 80000.0)  # 大按钮更像弹窗按钮
#         cls = _class_name(c).lower()
#         type_bonus = 1.0 if "button" in cls else (0.6 if "pane" in cls else 0.4)
#         score = 2.2 * center_bonus + 1.2 * size_bonus + type_bonus
#         cand = (score, c, name, (l, t, r, b))
#         if (best is None) or (score > best[0]):
#             best = cand

#     if not best:
#         return False

    # score, node, name, (l, t, r, b) = best
    # print(f"[CONSENT-DLG] click '{name}' rect=({l},{t},{r},{b}) score={score:.2f}")
    # return _ascend_click(mini_win, node)

def auto_consent_dialog(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
    """点击弹窗中的“同意/允许/确认/继续”等**正向**按钮（避开负向 & 排除‘已阅读并同意…’文案行）"""
    gw = cfg["global_consent"]
    agree = gw["agree_words"]
    neg = gw["negative_words"]
    exclude = gw.get("dialog_exclude_words", [])

    W = mini_win.rectangle()
    cx_win = (W.left + W.right) / 2.0
    cy_win = (W.top + W.bottom) / 2.0
    diag = max(1.0, ((W.right - W.left)**2 + (W.bottom - W.top)**2) ** 0.5)

    best = None
    for c in mini_win.descendants():
        if not _visible(c):
            continue
        name = _text(c)
        if not name:
            continue
        # 只接收包含正向词，且不包含负向 & 排除词
        if not any(w in name for w in agree):
            continue
        if _is_negative_text(name, neg):
            continue
        if any(x in name for x in exclude):
            continue

        l, t, r, b = _rect(c)
        x_mid, y_mid = (l + r) / 2.0, (t + b) / 2.0
        area = (r - l) * (b - t)
        # 打分：越靠中心/越大越好；强偏向 Button
        center_bonus = 1.0 - min(1.0, (((x_mid - cx_win)**2 + (y_mid - cy_win)**2) ** 0.5) / diag)
        size_bonus = min(1.0, area / 90000.0)  # 大号主按钮
        cls = _class_name(c).lower()
        type_bonus = 1.3 if "button" in cls else (0.7 if "pane" in cls else 0.3)
        score = 2.4 * center_bonus + 1.4 * size_bonus + type_bonus

        if (best is None) or (score > best[0]):
            best = (score, c, name, (l, t, r, b))

    if not best:
        return False

    score, node, name, (l, t, r, b) = best
    print(f"[CONSENT-DLG] click '{name}' rect=({l},{t},{r},{b}) score={score:.2f}")
    log_ui_event(f"click:{name}", "profile_candidate", mini_win)
    return _ascend_click(mini_win, node)

def click_primary_cta_after_consent(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
    """当页面存在‘已阅读并同意…’等文案时，优先点击同一层/同一弹窗里的主按钮（登录/继续/授权…）"""
    gw = cfg["global_consent"]
    cta_words = gw.get("primary_cta_words", [])
    neg = gw["negative_words"]

    W = mini_win.rectangle()
    cx, cy = (W.left + W.right) / 2.0, (W.top + W.bottom) / 2.0
    diag = max(1.0, ((W.right - W.left)**2 + (W.bottom - W.top)**2) ** 0.5)

    best = None
    for c in mini_win.descendants():
        if not _visible(c):
            continue
        name = _text(c)
        if not name:
            continue
        if not any(w in name for w in cta_words):
            continue
        if _is_negative_text(name, neg):
            continue
        l, t, r, b = _rect(c)
        area = (r - l) * (b - t)
        # 主按钮通常在下半区、居中、面积较大
        center = 1.0 - min(1.0, (((((l + r) / 2.0) - cx) ** 2 + (((t + b) / 2.0) - cy) ** 2) ** 0.5) / diag)
        size = min(1.0, area / 80000.0)
        cls = _class_name(c).lower()
        type_bonus = 1.2 if "button" in cls else (0.6 if "pane" in cls else 0.3)
        score = 2.0 * center + 1.4 * size + type_bonus

        if (best is None) or (score > best[0]):
            best = (score, c, name, (l, t, r, b))

    if not best:
        return False

    score, node, name, (l, t, r, b) = best
    print(f"[CONSENT-CTA] click '{name}' rect=({l},{t},{r},{b}) score={score:.2f}")
    log_ui_event(f"click:{name}", "profile_candidate", mini_win)
    return _ascend_click(mini_win, node)


def _consent_still_present(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
    """简单判断是否仍存在‘隐私/同意/协议’的痕迹（用于点击后复检）"""
    gw = cfg["global_consent"]
    words = gw["consent_text_words"] + gw["agree_words"]
    joined = " ".join((_text(c) or "") for c in mini_win.descendants())
    return any(w in joined for w in words)

# def handle_global_consent(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
#     """
#     全局守门员：尝试 N 轮，优先处理复选圈，其次处理弹窗按钮。
#     任一轮有动作就算成功；若点击后仍检测到同意相关文本，则继续下一轮（最多 guard_rounds）
#     """
#     rounds = int(cfg["general"].get("guard_rounds", 3))
#     acted = False
#     for i in range(rounds):
#         did = False
#         # A) 先尝试复选圈（更安全，不会误点拒绝）
#         if auto_consent_checkbox(mini_win, cfg):
#             did = True
#             acted = True
#             time.sleep(0.5)
#         # B) 再尝试弹窗按钮（只点“同意/允许/继续/知道了”，并自动避开拒绝类）
#         if auto_consent_dialog(mini_win, cfg):
#             did = True
#             acted = True
#             time.sleep(0.8)
#         # 点击后复检：没有“同意/隐私/协议”痕迹就停
#         if did:
#             if not _consent_still_present(mini_win, cfg):
#                 print("[CONSENT] 清理完成")
#                 break
#             else:
#                 print("[CONSENT] 仍检测到相关文案，继续下一轮…")
#         else:
#             break
#     return acted
def handle_global_consent(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
    """
    全局守门员：尝试 N 轮：
      1) 勾选“已阅读并同意 …”前的圈；
      2) 立即尝试点击“主按钮（手机号快捷登录/一键登录/继续/授权登录…）”；
      3) 再尝试点击对话框正向按钮；
      4) 每轮后复检，直到消失或到达最大轮数。
    """
    rounds = int(cfg["general"].get("guard_rounds", 3))
    acted = False
    for i in range(rounds):
        did_something = False

        # A) 勾选复选圈
        if auto_consent_checkbox(mini_win, cfg):
            did_something = True
            acted = True
            time.sleep(0.3)

        # B) 勾选后优先点“主按钮”（手机号快捷登录/一键登录/继续等）
        if click_primary_cta_after_consent(mini_win, cfg):
            did_something = True
            acted = True
            time.sleep(0.6)

        # C) 兜底：弹窗正向按钮（排除‘已阅读并同意…’）
        if auto_consent_dialog(mini_win, cfg):
            did_something = True
            acted = True
            time.sleep(0.6)

        # 复检：是否还有“同意/协议/隐私”等痕迹
        if did_something:
            if not _consent_still_present(mini_win, cfg):
                print("[CONSENT] 清理完成")
                
                break
            else:
                print("[CONSENT] 仍检测到相关文案，继续下一轮…")
        else:
            break

    return acted


# =========================
# 步骤编排
# =========================
# def auto_go_profile(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> bool:
#     c = cfg["step_profile"]; g = cfg["general"]
#     return click_by_keywords(mini_win,
#                              keywords=c["keywords"],
#                              sentinels=c["sentinels"],
#                              topk=g["topk"], try_k=g["try_k"], click_timeout=g["click_timeout"],
#                              step_name="STEP1:PROFILE")

def auto_go_profile(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> int:
    c = cfg["step_profile"]; g = cfg["general"]

    # ① 尝试“底部 Tab 精准点击”
    hit_tab = click_bottom_profile_tab(
        mini_win,
        keywords=c["keywords"],
        bottom_ratio=c.get("roi_bottom_ratio", 0.32),
        max_text_len=c.get("max_text_len", 6),
        topk=6,
        click_timeout=4.5
    )
    print(hit_tab)
    if hit_tab == 1:
        return 1
    elif hit_tab == 2:
        return 2
    else:
        # 如果底部 tab 试过没成功，可能误进了别的二级页（比如“直播”）
        safe_back(mini_win)

    # ② 回退后再用“通用关键词点击”（你原来的逻辑）
    ok = click_by_keywords(mini_win,
                           keywords=c["keywords"],
                           sentinels=c["sentinels"],
                           topk=g["topk"], try_k=g["try_k"], click_timeout=g["click_timeout"],
                           step_name="STEP1:PROFILE")
    if ok == 0:
        # 再回退一次，保持环境“可恢复”
        safe_back(mini_win)
    return ok

def auto_login_entry(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> int:
    c = cfg["step_login_entry"]; g = cfg["general"]
    return click_by_keywords(mini_win,
                             keywords=c["keywords"],
                             sentinels=c["sentinels"],
                             topk=g["topk"], try_k=g["try_k"], click_timeout=g["click_timeout"],
                             step_name="STEP2:LOGIN_ENTRY")

def auto_login_onetap(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> int:
    c = cfg["step_onetap"]; g = cfg["general"]
    return click_by_keywords(mini_win,
                             keywords=c["keywords"],
                             sentinels=c["sentinels"],
                             topk=g["topk"], try_k=g["try_k"], click_timeout=g["click_timeout"],
                             step_name="STEP3:ONE_TAP")

# =========================
# 配置加载 & 流程入口
# =========================
def load_cfg(path: Optional[str]) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if path and os.path.exists(path):
        try:
            user = json.load(open(path, "r", encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and k in cfg:
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            print(f"[CFG] loaded from {path}")
        except Exception as e:
            print(f"[CFG] load error: {e} -> using defaults")
    return cfg

def run_pipeline(mini_win: BaseWrapper, cfg: Dict[str, Any]) -> None:
    # 进入任何步骤前/后都跑一次全局“同意/授权”守门员
    handle_global_consent(mini_win, cfg)

    ok1 = auto_go_profile(mini_win, cfg)
    handle_global_consent(mini_win, cfg)
    if ok1 == 0:
        print("[PIPE] 步骤1失败（未能到个人/我的页）")
        return
    if ok1 == 2 :
        print("[PIPE] 登录成功")
        return

    ok2 = auto_login_entry(mini_win, cfg)
    handle_global_consent(mini_win, cfg)
    if ok2 ==0:
        print("[PIPE] 步骤2失败（未找到登录入口），可能已登录或文案不同")
        return

    # 再清一次（不少 App 会在登录页或“登录前”再弹隐私/授权）
    handle_global_consent(mini_win, cfg)

    ok3 = auto_login_onetap(mini_win, cfg)
    handle_global_consent(mini_win, cfg)
    if ok3 == 0:
        print("[PIPE] 步骤3未命中一键登录（可能没有该按钮或需要短信登录）")
    else:
        print("[PIPE] 一键登录流程已尝试。")
        

# 在 autotest_login.py 中添加（或替换原有 __main__ 块）
def run_all_programs(program_list_path="dataset\\mini_programs.txt", config_path=None):
    """遍历 program list，调用 run_automation_test + run_pipeline"""
    program_list = read_program_list(program_list_path)
    try:
        for program_name in program_list:
            mini_win = run_automation_test(program_name)
            if mini_win:
                cfg = load_cfg(config_path)
                run_pipeline(mini_win, cfg)
                time.sleep(30)
    except Exception as e:
        print("run_all_programs 中发生异常:", e)
        raise

# =========================
# 直接运行（你已有 run_automation_test）
# =========================
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Mini UIA Profile/Login pipeline with global consent guard")
    ap.add_argument("--config", default=None, help="外部JSON配置路径（可选）")
    args = ap.parse_args()
    program_list = read_program_list("dataset\\mini_programs.txt")
    # run_automation_begin()
    # 你已有的：返回小程序窗口
    try:
        for program_name in program_list:

            mini_win = run_automation_test(program_name)
            if mini_win:
                cfg = load_cfg(args.config)
                run_pipeline(mini_win, cfg)
    except NameError:
        raise RuntimeError("请先提供 run_automation_test()，返回 mini_win 窗口对象。")






