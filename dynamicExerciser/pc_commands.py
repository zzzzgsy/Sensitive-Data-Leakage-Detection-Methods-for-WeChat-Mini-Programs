# dynamicExerciser/pc_commands.py
from asyncio import subprocess
import os
import time, pathlib, shutil
from PIL import ImageGrab
import dynamicExerciser.mini_app_utils_pc as mini_app_utils
from pywinauto import Desktop, keyboard,Application
import config
import psutil
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.base_wrapper import BaseWrapper
import sys
sys.path.append(r'G:\miniapp\XPOScope-main')
from OcrDump import ocr_recognition_pc as ocr_recognition
from pywinauto import mouse
# ====== 1) 绑定与尺寸 ======
_WECHAT_WIN = None
_VIEW_RECT = None  # (left, top, right, bottom)
_mini_win = None

# ============ 可调参数（放到 config.py 也行） ============
# 主窗口标题（中/英都试）
WECHAT_TITLE = getattr(config, "WECHAT_TITLE", "微信")
# 搜索框点击偏移（相对“窗口中心”偏移，按你能跑的数值）
SEARCH_OFFSET_X = getattr(config, "WECHAT_SEARCH_OFFSET_X", 380)
SEARCH_OFFSET_Y = getattr(config, "WECHAT_SEARCH_OFFSET_Y", -395)
# 搜索结果第一个条目偏移（相对“窗口中心”偏移）
RESULT_OFFSET_X = getattr(config, "WECHAT_RESULT_OFFSET_X", -250)
RESULT_OFFSET_Y = getattr(config, "WECHAT_RESULT_OFFSET_Y", -300)
# 视图留白（裁边），避免截到边框/标题栏
VIEW_PADDING = getattr(config, "WECHAT_VIEW_PADDING", (20, 80, 20, 60))  # left, top, right, bottom
# 可选：微信可执行路径（没开就帮你拉起）
WECHAT_EXE = getattr(config, "WECHAT_EXE", None)
def restart_miniprogram(program_name: str):
    global _mini_win
    if _mini_win is not None:
        try:
            _mini_win.set_focus()
            W, H = config.DEVICE_WIDTH, config.DEVICE_HEIGHT
            # 标题栏高度大约 7%H，返回箭头大概在左侧 4–6%W
            cx = int(0.95 * W)
            cy = int(0.05 * H)
            mouse.move(coords=_to_screen_xy(cx, cy))
            mouse.click(button='left', coords=_to_screen_xy(cx, cy))
            time.sleep(1)
            # 点击小程序的菜单按钮
            adb_click(1100, 55)
            time.sleep(1)
            # 点击“重新打开小程序”
            adb_click(910, 360)
            time.sleep(3)
            restart_mini_win = Desktop(backend="uia").window(title_re=f".*{program_name}.*")
            if restart_mini_win.exists():
                _bind_view_rect_from_window(restart_mini_win)  # ★ 绑定到小程序窗口，这样后续截图/点击都在小程序内        
                _mini_win=restart_mini_win
            return _mini_win
        except Exception:
            pass
    print("error")
    # _bind_view_rect_from_window(win_spec)
    return None

def _start_wechat_if_needed():
    if any((p.info["name"] or "").lower()=="wechat.exe" for p in psutil.process_iter(["name"])):
        return
    if WECHAT_EXE and os.path.exists(WECHAT_EXE):
        subprocess.Popen([WECHAT_EXE], shell=False)
        time.sleep(3)

def _find_main_window(name):
    """运行自动化测试（pywinauto）"""
    windows = Desktop(backend="uia").windows()
    print("_find_main_window")
    PID = None
    for w in windows:
        try:
            title = w.window_text()
            pid = w.process_id()
            cls = w.friendly_class_name()
            if title == "微信":
                if cls == 'Pane' and title == name :
                    PID = pid
                    return w
                # break
            else:  
                if title == name:
                    return w
        except Exception as e:
            print("无法读取窗口信息:", e)

    print("未找到微信窗口，请确保微信已打开")
    return None

def _bind_view_rect_from_window(win):
    global _WECHAT_WIN, _VIEW_RECT
    _WECHAT_WIN = win
    try: win.set_focus()
    except: pass
    r = win.rectangle()
    padL, padT, padR, padB = VIEW_PADDING
    # _VIEW_RECT = (r.left+padL, r.top+padT, r.right-padR, r.bottom-padB)
    _VIEW_RECT = (r.left, r.top, r.right, r.bottom)
    print(_VIEW_RECT[0], _VIEW_RECT[1], _VIEW_RECT[2], _VIEW_RECT[3])
    # 把内容区宽高同步给 config，保证后续相对坐标正确
    config.DEVICE_WIDTH  = _VIEW_RECT[2]-_VIEW_RECT[0]
    config.DEVICE_HEIGHT = _VIEW_RECT[3]-_VIEW_RECT[1]
    print(config.DEVICE_WIDTH)
    print(config.DEVICE_HEIGHT)

def _ensure_wechat(timeout=10):
    """仅确保有一个可用窗口（小程序或主窗口），并设置 _VIEW_RECT"""
    global _WECHAT_WIN, _VIEW_RECT
    if _WECHAT_WIN is not None and _VIEW_RECT is not None:
        return _WECHAT_WIN, _VIEW_RECT
    _start_wechat_if_needed()
    t0 = time.time()
    last = None
    while time.time()-t0 < timeout:
        win = _find_main_window("微信")
        if win:
            _bind_view_rect_from_window(win)
            return _WECHAT_WIN, _VIEW_RECT
        time.sleep(0.3)
    raise RuntimeError("未找到微信主窗口，请确认已登录")


def open_miniprogram(program_name: str):
    """用你那套逻辑：锁定微信主窗→点搜索→输入→回车→点第一个结果→聚焦小程序窗→绑定 VIEW_RECT"""
    # 1) 锁定主窗口
    _ensure_wechat()
    # 2) 用 process id 连接 app & 获取 spec
    pid = _WECHAT_WIN.process_id()
    app = Application(backend="uia").connect(process=pid)
    win_spec = app.window(title=WECHAT_TITLE)
    try: win_spec.set_focus()
    except: pass
    rect = win_spec.rectangle()
    # 3) 计算点击坐标（基于窗口中心 + 偏移）
    abs_x = (rect.left + rect.right)//2
    abs_y = (rect.top  + rect.bottom)//2
    # search_x = abs_x + SEARCH_OFFSET_X
    # search_y = abs_y + SEARCH_OFFSET_Y
    search_x = abs_x - rect.left + 380
    search_y = abs_y - rect.top - 395
    # 4) 点击搜索框并输入名称
    print(f"正在处理小程序: {program_name}")
    print(program_name)
    # 点击搜索框
    win_spec.click_input(coords=(search_x, search_y))
    # 输入名称
    win_spec.type_keys(program_name, with_spaces=True)
    win_spec.type_keys("{ENTER}")
    time.sleep(3)
    # 5) 点击第一个搜索结果
    res_x = abs_x - rect.left - 250
    res_y = abs_y - rect.top - 300
    # mini_app_utils.create_opt_file()
    mini_app_utils.write_last_opt(999999)   # 让启动阶段流量至少能对齐到 opt=0
    win_spec.click_input(coords=(res_x, res_y))
    ts = time.time()
    print("✅ 已点击，尝试打开小程序！")
    
    time.sleep(5)
    # 打印所有窗口名称
    all_windows = Desktop(backend="uia").windows()
    print("当前所有窗口：")
    for w in all_windows:
        try:
            title = w.window_text()
            print(f" - 窗口标题: {title}")
        except Exception as e:
            print("无法读取窗口信息:", e)
    # # 6) 尝试找到小程序窗口（标题含程序名）
    try:
        mini_win = Desktop(backend="uia").window(title_re=f".*{program_name}.*")
        if mini_win.exists():
            _bind_view_rect_from_window(mini_win)  # ★ 绑定到小程序窗口，这样后续截图/点击都在小程序内
            global _mini_win
            _mini_win=mini_win
            return mini_win,ts
    except Exception:
        # pass
        # 输出错误信息
        import traceback
        traceback.print_exc()   
    # 兜底：仍用主窗口
    print("error")
    # _bind_view_rect_from_window(win_spec)
    return None,0

# 放在文件末尾截图函数附近
def adb_cache_screenshot():
    # 抓一张临时图到 SCREENSHOT_CACHE_PATH/temp.png
    # _ensure_wechat()
    # set_focus()
    img = ImageGrab.grab(bbox=_VIEW_RECT)
    cache_dir = pathlib.Path(config.SCREENSHOT_CACHE_PATH)
    cache_dir.mkdir(parents=True, exist_ok=True)
    img.save(str(cache_dir / "temp.png"))

def init_device_wh():
    from config import DEVICE_WIDTH, DEVICE_HEIGHT
    _, rect = _WECHAT_WIN, _VIEW_RECT
    w = rect[2]-rect[0]
    h = rect[3]-rect[1]
    import config
    config.DEVICE_WIDTH = w
    config.DEVICE_HEIGHT = h

# ====== 2) 点击 / 按键 ======
def _to_screen_xy(x, y):

    # _mini_win.set_focus()
    _, (L,T,R,B) = _WECHAT_WIN, _VIEW_RECT
    return int(L + x), int(T + y)


# def adb_click(x, y):  # 保持原名
#     print(f"点击坐标: ({x}, {y})")
#     sx, sy = _to_screen_xy(x, y)
#     _mini_win.set_focus()
#     mouse.move(coords=(sx, sy))
#     mouse.click(button='left', coords=(sx, sy))
    
def adb_click(x, y, *, return_ts=False):  # 保持原名，新增 return_ts 开关
    print(f"点击坐标: ({x}, {y})")
    sx, sy = _to_screen_xy(x, y)
    try:
        _WECHAT_WIN.set_focus()  # 或你那边的 _mini_win / win_spec；保持你现有变量
    except Exception:
        pass
    mouse.move(coords=(sx, sy))
    # ★ 在真正发起点击的“同一时刻”采样时间
    ts_click = time.time()
    mouse.click(button='left', coords=(sx, sy))
    if return_ts:
        return ts_click


# def adb_click_sleep(x, y, sec=0.4):
#     _mini_win.set_focus()
#     adb_click(x, y)
#     time.sleep(sec)
def adb_click_sleep(x, y, sec=0.4, *, return_ts=False):
    ts_click = adb_click(x, y, return_ts=True)
    time.sleep(sec)
    if return_ts:
        return ts_click
# 安卓键值常量兼容（最少这几个）
KEYCODE_BACK   = 4
KEYCODE_ENTER  = 66
KEYCODE_SWITCH_APP = 187

def adb_key_event(code):
    if code == KEYCODE_BACK:
        keyboard.send_keys('{ESC}')      # 或 Alt+Left
    elif code == KEYCODE_ENTER:
        keyboard.send_keys('{ENTER}')
    elif code == KEYCODE_SWITCH_APP:
        # PC 无多任务键，这里 NO-OP 或者 Alt+Tab
        pass
    else:
        pass
# adb_commands.py
def click_header_back_hotzone():
    """点击标题栏左上角的返回热区（不依赖图像识别）"""
    try:
        _WECHAT_WIN.set_focus()
    except Exception:
        pass
    W, H = config.DEVICE_WIDTH, config.DEVICE_HEIGHT
    # 标题栏高度大约 7%H，返回箭头大概在左侧 4–6%W
    cx = int(0.05 * W)
    cy = int(0.05 * H)
    mouse.move(coords=_to_screen_xy(cx, cy))
    mouse.click(button='left', coords=_to_screen_xy(cx, cy))
# mini_app_auto_pc.py（或 target_resolver/ocr 模块更合适）


def switch_to_adb_keyboard():
    # PC 无此概念，直接 NO-OP
    pass

def oneplus_wx_enter():
    keyboard.send_keys('{ENTER}')

# ====== 3) 截图 / 文件操作（路径沿用原有 config 约定）======


# def adb_screenshot(index):
#     # _ensure_wechat()
#     # _find_main_window()
#     bbox = _VIEW_RECT

#     img = ImageGrab.grab(bbox=bbox)
#     out = pathlib.Path(config.SCREENSHOT_PATH) / f"{index}.png"
#     out.parent.mkdir(parents=True, exist_ok=True)
#     img.save(str(out))

def adb_screenshot(index):
    bbox = _VIEW_RECT
    time.sleep(2)
    print("[DEBUG adb_screenshot] _VIEW_RECT:", bbox)  # (left, top, right, bottom)

    img = ImageGrab.grab(bbox=bbox)
    print("[DEBUG adb_screenshot] img.size:", img.size)  # (width, height)

    out = pathlib.Path(config.SCREENSHOT_PATH) / f"{index}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))

def rename_screenshot(temp_index, new_index):
    src = pathlib.Path(config.SCREENSHOT_PATH) / f"{temp_index}.png"
    dst = pathlib.Path(config.SCREENSHOT_PATH) / f"{new_index}.png"
    if src.exists(): shutil.move(str(src), str(dst))

def del_screenshot(temp_index):
    p = pathlib.Path(config.SCREENSHOT_PATH) / f"{temp_index}.png"
    if p.exists(): p.unlink()

def _rename_temp_ocr_jsons_to_index(page_idx: int):
    base = config.PAGE_TEXT_PATH
    mapping = [
        (os.path.join(base, "ocr_raw_temp.json"), os.path.join(base, f"ocr_raw_{page_idx}.json")),
        (os.path.join(base, "ocr_temp.json"),     os.path.join(base, f"ocr_{page_idx}.json")),
        (os.path.join(base, "ocr_sorted_temp.json"), os.path.join(base, f"ocr_sorted_{page_idx}.json")),
    ]
    for src, dst in mapping:
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except Exception:
                pass
