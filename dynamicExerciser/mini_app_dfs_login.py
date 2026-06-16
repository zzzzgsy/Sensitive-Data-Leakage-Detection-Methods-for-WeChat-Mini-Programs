# ===== 登录 DFS 配置（规则为主） =====
import time
import config
import pc_commands as adb_commands
import mini_app_utils_pc as mini_app_utils
from page_utils.Page import Page
from page_utils.PageGraph import PageGraph
import sys
sys.path.append(r'G:\miniapp\XPOScope-main')
from OcrDump import ocr_recognition_pc as ocr_recognition
import mini_app_auto_pc as mini_app_auto
DFS_CFG = {
    "step_profile": {
        "keywords": ["我的", "个人", "个人中心", "我", "个人信息", "信息", "账号", "帐户", "资料", "设置"],
        "sentinels": ["个人信息", "手机号", "手机验证", "验证码", "昵称", "绑定", "账号", "帐户", "登录"]
    },
    "step_login_entry": {
        "keywords": ["授权登录", "登录", "立即登录", "账号登录", "帐号登录", "手机号登录", "短信登录", "验证码登录", "微信登录"],
        "sentinels": ["手机号", "验证码", "短信", "密码", "一键登录", "本机号码", "同意并继续", "授权"]
    },
    "step_onetap": {
        "keywords": ["一键登录", "快捷授权登录","授权登录","快捷登录","一键授权登录","允许", "手机号快捷登录","本机号码一键登录",
                      "手机号一键登录","本机号码登录", "本机号码一键绑定","手机号绑定",
                     "一键绑定", "本机号码验证", "本机号码一键绑定", "同意并继续"],
        "sentinels": ["已登录","已实名", "退出登录", "绑定成功", "已绑定", "尾号","3322"]
    },
    # 每一步 DFS 的最大深度（点击层数），防止走太远
    "max_depth": 3
}

CONSENT_KEYWORDS = [
    "已阅读并同意", "我已阅读并同意", "同意并继续", "同意并授权",
    "同意隐私政策", "同意用户协议", "同意协议", "已阅读并知悉",
]

def click_consent_if_any(mini_app: mini_app_auto.MiniAppAuto, page: Page) -> Page:
    """在当前 page 上尝试点击一次“同意/协议”相关控件，并返回点击后的新页（或原页）"""
    if not page or not page.page_dump_str:
        return page

    txt = "".join(page.page_dump_str)
    if not any(k in txt for k in CONSENT_KEYWORDS):
        return page   # 页面根本没有这种文字，直接返回

    # 用一层很浅的 DFS（depth=1），strict_text=True 避免乱点
    new_page = _dfs_step_by_keywords(
        mini_app,
        page,
        CONSENT_KEYWORDS,
        step_sentinels=[],   # 是否点中不用 sentinel 来判断
        max_depth=1,
        strict_text=True,
    )
    return new_page or page


def _page_has_any_keyword(page: Page, keywords) -> bool:
    """判断页面 dump 文本里是否包含任一关键词，作为哨兵（已到达目标页的判断）"""
    if not page or not page.page_dump_str:
        return False
    joined = "".join(page.page_dump_str)
    return any(k in joined for k in keywords)

def _score_click_for_keywords(page: Page,
                              idx: int,
                              keywords,
                              strict_text: bool = False,
                              extra_boost_keywords=None) -> float:
    """
    给某个 click_location 按“文字命中 + 底部优先 + 按钮大小”打分。

    :param keywords: 本步骤目标关键词列表
    :param strict_text: True 时，未命中任何关键词则直接返回 0 分
    :param extra_boost_keywords: 额外加权关键词子串列表，如 ["一键","本机号码","快捷"]
    """
    if idx < 0 or idx >= len(page.click_locations):
        return 0.0
    x, y = page.click_locations[idx]
    meta = page.get_click_meta(x, y) or {}
    text = (meta.get("text") or "").strip()
    bbox = meta.get("bbox") or [x, y, x, y]

    score = 0.0
    if not text and not bbox:
        return score

    # ① 文字命中度
    hit_kw = None
    for i, kw in enumerate(keywords):
        if kw and kw in text:
            hit_kw = kw
            # 基础分：越靠前的关键字权重越高
            score += 3.0 + 0.05 * (len(keywords) - i)
            break

    # 如果要求严格匹配但没命中任何关键词，直接放弃
    if strict_text and hit_kw is None:
        return 0.0

    # 针对“一键/本机号码/快捷”等再额外加一点权重
    if hit_kw and extra_boost_keywords:
        if any(sub in hit_kw for sub in extra_boost_keywords):
            score += 3.0   # 这个数字你可以按需要调大/调小

    # ② 底部优先（Tab栏、大按钮一般在底部）
    try:
        x1, y1, x2, y2 = bbox
        cy = (y1 + y2) / 2.0
    except Exception:
        cy = y
        y1, y2 = y, y
    H = float(config.DEVICE_HEIGHT or 1)
    bottomness = max(0.0, min(1.0, (cy / H)))
    score += 1.5 * bottomness

    # ③ 按钮面积（大一点的按钮更可能是重要操作）
    try:
        area = max(1.0, (x2 - x1) * (y2 - y1))
        area_bonus = min(1.0, area / 80000.0)
        score += 0.8 * area_bonus
    except Exception:
        pass

    return score


import mini_app_utils_pc as mini_app_utils
import pc_commands as adb_commands
from OcrDump import ocr_recognition_pc as ocr_recognition

def _click_build_page(mini_app: mini_app_auto.MiniAppAuto,
                      from_page: Page,
                      click_index: int) -> Page | None:
        # 点击预算控制
    if hasattr(mini_app, "login_dfs_clicks"):
        mini_app.login_dfs_clicks += 1
        if mini_app.login_dfs_clicks > getattr(mini_app, "login_dfs_click_budget", 10):
            print("[DFS] login click budget exceeded, stop DFS.")
            return None
    """
    在 from_page 上点第 click_index 个坐标：
      - 记录 opt_id / ui_actions
      - 调 create_normal_page
      - 写 page_text / opt_image_map
    返回新页面 Page（不管是否“新页”），失败返回 None
    """
    if click_index < 0 or click_index >= len(from_page.click_locations):
        return None

    click_x, click_y = from_page.click_locations[click_index]
    meta = from_page.get_click_meta(click_x, click_y) or {}
    if meta:
        tgt_text = meta.get("text","")
        tgt_bbox = meta.get("bbox",[click_x,click_y,0,0])
    else:
        tgt_text, tgt_bbox = "", [int(click_x), int(click_y), 0, 0]     

    print(f"[DFS] click idx={click_index}, xy=({click_x},{click_y}), text='{tgt_text}'")

    # visit_key = f"{tgt_text}"
    #     # 如果 key 在历史中，且文本不为空（防止误杀无文本按钮），则跳过
    #     # 或者你希望严格去重，连无文本的也跳过，就去掉 'and tgt_text'
    # if (visit_key in visited_elements) and tgt_text:
    #     print(f"[BFS] Skip visited single-node: {tgt_text}")
    #     return None # 或者视情况处理
    #     # 执行点击
        
    # 3. 【新增】记录到全局历史
    # mini_app_utils.save_visited_element(target_page.index, tgt_text, (click_x, click_y))
    mini_app_utils.save_visited_element( tgt_text, (click_x, click_y))
    # 写入操作记录
    # time.sleep(0.5)
    # 真正点击（取同一时刻 ts）
    t_click = adb_commands.adb_click(click_x, click_y, return_ts=True)

    # 写 last_opt（和 BFS 一样）
    mini_app_utils.write_last_opt(mini_app.opt_count)
    # 更新 click_index（避免 BFS 之后重复点击）
    if from_page.click_index <= click_index:
        from_page.click_index = click_index + 1

    # 截屏 + OCR + 建新页
    is_new_page, new_or_similar_page = mini_app.create_normal_page(click_index, from_page)

    # 把新页文本写入 page_text，并建立 opt->image 映射
    mini_app_utils.write_page_text(mini_app.opt_count, new_or_similar_page.page_dump_str)
    mini_app_utils.append_opt_image_map(mini_app.opt_count, new_or_similar_page.index)

    # 记录 UI 动作
    try:
        mini_app_utils._append_ui_action(
            opt_id=mini_app.opt_count,
            page_before=from_page.index,
            page_after=new_or_similar_page.index,
            click_xy=(click_x, click_y),
            click_index=click_index,
            screenshot_index=new_or_similar_page.index,
            target_text=tgt_text,
            target_bbox=tgt_bbox,
            ts=t_click
        )
    except Exception as e:
        print(f"[DFS] write ui_action failed: {e}")

    mini_app.opt_count += 1
    return new_or_similar_page


def _dfs_step_by_keywords(mini_app: mini_app_auto.MiniAppAuto,
                          start_page: Page,
                          step_keywords,
                          step_sentinels,
                          max_depth: int = 3,
                          visited_md5: set | None = None,
                          depth: int = 0,
                          strict_text: bool = False,
                          extra_boost_keywords=None) -> Page | None:
    """
    从 start_page 开始，按 step_keywords 优先点击，深度优先搜索，
    直到页面包含 step_sentinels（认为达成该步骤），或达到 max_depth。
    返回“命中的页面 Page”，否则 None。
    """
    if visited_md5 is None:
        visited_md5 = set()

    if not start_page or not start_page.page_md5:
        return None

    if start_page.page_md5 in visited_md5:
        return None
    visited_md5.add(start_page.page_md5)

    print(f"[DFS] depth={depth}, page={start_page.index}, md5={start_page.page_md5}")

    # 1) 先看是否命中本步骤的哨兵（比如 Step1 的 “个人信息/手机号/账号/登录”）
    if step_sentinels and _page_has_any_keyword(start_page, step_sentinels):
        print(f"[DFS] sentinels hit on page {start_page.index}")
        return start_page

    if depth >= max_depth:
        return None
    
    # 当前页是否已经满足哨兵（比如一打开就已在个人中心 / 登录页）
    # if _page_has_any_keyword(start_page, step_sentinels):
    #     print(f"[DFS] sentinels hit on page {start_page.index}")
    #     return start_page
    
    if _is_login_done_page(start_page):
        print(f"[DFS] login-entry page {start_page.index} already logged-in.")
        return start_page
    
    _is_login_done_page

    if depth >= max_depth:
        return None

    # 计算每个点击点的得分（按关键字匹配+位置）
    scored = []
    for idx in range(len(start_page.click_locations)):
        s = _score_click_for_keywords(
            start_page,
            idx,
            step_keywords,
            strict_text=strict_text,
            extra_boost_keywords=extra_boost_keywords,
        )
        if s > 0:
            scored.append((s, idx))
    # for idx in range(len(start_page.click_locations)):
    #     s = _score_click_for_keywords(start_page, idx, step_keywords)
    #     if s > 0:
    #         scored.append((s, idx))
    # 按得分降序
    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        print(f"[DFS] no keyword-related clicks on page {start_page.index}")
        return None

    for score, idx in scored:
        print(f"[DFS] try click idx={idx} score={score:.2f} on page {start_page.index}")
        # 1) 执行点击 + 建新页（也会写证据链）
        new_page = _click_build_page(mini_app, start_page, idx)
        if not new_page:
            continue

        # 2) 新页面上先看哨兵
        if step_sentinels and _page_has_any_keyword(new_page, step_sentinels):
            print(f"[DFS] sentinels hit after click idx={idx}, page={new_page.index}")
            return new_page
        
        if _is_login_done_page(new_page):
            print(f"[DFS] sentinels hit after click idx={idx}, page={new_page.index}")
            return new_page

        # 3) 递归继续往下找
        sub = _dfs_step_by_keywords(
            mini_app,
            new_page,
            step_keywords,
            step_sentinels,
            max_depth=max_depth,
            visited_md5=visited_md5,
            depth=depth + 1
        )
        if sub is not None:
            return sub

        # 4) 如果这一条分支没找到目标，尝试回退到 start_page
        back_ok, back_page = mini_app.back(start_page, new_page)
        print(f"[DFS] back from page {new_page.index} -> ok={back_ok}, got page {getattr(back_page,'index',None)}")
        # 即便 back 不完全成功，也继续尝试下一 candidate，避免卡死

    return None
LOGIN_DONE_SENTINELS = [
    "注销账户", "退出登录",
    "已登录", "绑定成功", "已绑定", "尾号", "已实名", "3322","高书雅","高*雅","雅"
]
LOGIN_NOT_DONE_SENTINELS = [
    "请登录", "手机号一键登录",
    "点击登录", "请先登录", "登录后使用更多功能", "登录/注册",
    "登录", "注册", "授权登录", "立即登录",
]

   
# def _is_login_done_page(page: Page) -> bool:
#     if not page or not page.page_dump_str:
#         print("[DFS] _is_login_done_page: invalid page" )
#         return False
#     txt = "".join(page.page_dump_str)
#     has_done = any(k in txt for k in LOGIN_DONE_SENTINELS)
#     has_not_done = any(k in txt for k in LOGIN_NOT_DONE_SENTINELS)
#     # 至少要满足：有“注销/退出/已绑定/尾号”之类，同时没有明显“请登录/点击登录”等提示
#     return has_done or not has_not_done

def _is_login_done_page(page: Page) -> bool:
    if not page or not page.page_dump_str:
        print("[DFS] _is_login_done_page: invalid page")
        return False

    txt = "".join(page.page_dump_str)
    has_done     = any(k in txt for k in LOGIN_DONE_SENTINELS)
    has_not_done = any(k in txt for k in LOGIN_NOT_DONE_SENTINELS)

    # 调试输出，方便你看具体情况
    print(f"[DFS] _is_login_done_page page={page.index}, has_done={has_done}, has_not_done={has_not_done}")

    # 条件：有“已登录/退出/已实名/尾号”等，且没有“请登录/点击登录”等
    # return has_done or not has_not_done
    return has_done


def run_login_dfs(mini_app: mini_app_auto.MiniAppAuto, root_page: Page):
    """
    登录 DFS 阶段：
      - 返回 (logged_in: bool, login_page: Page | None)
    """
    cfg = DFS_CFG
    max_depth = cfg.get("max_depth", 3)

    # ----- 0) root 页面就已经是登录态？ -----
    if _page_has_any_keyword(root_page, LOGIN_DONE_SENTINELS):
        print("[DFS] root page already looks like logged-in page")
        return True, root_page
    # if _is_login_done_page(root_page):
    #     print(f"[DFS] root page already looks like logged-in page")
    #     return True, root_page

    # Step1: profile
    print("[DFS] STEP1: PROFILE")
    step1 = _dfs_step_by_keywords(
        mini_app,
        root_page,
        cfg["step_profile"]["keywords"],
        cfg["step_profile"]["sentinels"],
        max_depth=max_depth
    )
    # print(step1)
    if step1 is None:
        print("[DFS] STEP1 failed, maybe no profile tab / or already logged in in root.")
        return False, None
    
    # profile 页如果直接是登录态（你的这个小程序就是这种情况）
    if _is_login_done_page(step1):
        print(f"[DFS] profile page {step1.index} already logged-in, skip login-entry/one-tap.")
        return True, step1

    # Step2: login entry
    print("[DFS] STEP2: LOGIN ENTRY")
    step2 = _dfs_step_by_keywords(
        mini_app,
        step1,
        cfg["step_login_entry"]["keywords"],
        cfg["step_login_entry"]["sentinels"],
        max_depth=max_depth
    )
    if step2 is None:
        print("[DFS] STEP2 failed, maybe only profile but no explicit login.")
        return False, None

    if _is_login_done_page(step2):
        print(f"[DFS] login-entry page {step2.index} already logged-in.")
        return True, step2
    
    # Step3: 一键登录 / 本机号码
    print("[DFS] STEP3: ONE-TAP LOGIN")
    step3 = _dfs_step_by_keywords(
        mini_app,
        step2,
        cfg["step_onetap"]["keywords"],
        cfg["step_onetap"]["sentinels"],
        max_depth=max_depth,
        strict_text=True,                 # 注意：这里严格要求命中“一键/本机号码”等
        extra_boost_keywords=["一键", "快捷","手机号","本机号码"]  # 额外加权,
    )
    if step3 is None:
        print("[DFS] STEP3 not found, maybe only SMS login or user cancelled.")
        return False, step2

    if _is_login_done_page(step3):
        print(f"[DFS] login dfs finished at page {step3.index} (logged-in).")
        return True, step3

    # 理论上很难走到这里，但兜底一下
    return False, step3