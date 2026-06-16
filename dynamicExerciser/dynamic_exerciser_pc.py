import pathlib
import sys
import time

import eventlet

import config
# import mini_app_auto_pc
from page_utils.Page import Page
import adb_commands
import mini_app_utils_pc as mini_app_utils
import mini_app_auto_pc as mini_app_auto
import pc_commands as adb_commands
import target_resolver
import sys
sys.path.append(r'G:\miniapp\XPOScope-main')
from OcrDump import ocr_recognition_pc as ocr_recognition
# 顶部 imports 处补充
import json, os
def reset_all_page_click_index(page_graph):
    """
    DFS 结束后，把所有页面的 click_index 重置成 0，
    让 BFS 可以从每个页面的第一个点击点开始重新遍历。
    """
    for page_node in page_graph.all_page_nodes:
        page_node.page.click_index = 0

def dfs_bfs_auto_run(app_package, mini_app_plat, mini_app_name, mobile_model):
    import mini_app_dfs_login
    enqueue = []
    print(f"开始测试小程序 {mini_app_name} ......")
    mini_app = mini_app_auto.MiniAppAuto(app_package, mini_app_plat, mini_app_name, mobile_model)
    root_page = mini_app.start_mini_app()
    
    # print(f"[MAIN] root page={root_page.index}, clicks={len(root_page.click_locations)}")
    # ===== 1) DFS 登录阶段 =====
    # mini_app_dfs_login.run_login_dfs(mini_app, root_page)
    # ===== 1) DFS 登录阶段 =====
    logged_in, login_page = mini_app_dfs_login.run_login_dfs(mini_app, root_page)
    
    print(f"[MAIN] DFS login result: logged_in={logged_in}, login_page={getattr(login_page,'index',None)}")
    time.sleep(10)
    reset_all_page_click_index(mini_app.page_graph)
    # ===== 2) BFS 探索阶段 =====
    enqueue = [root_page]
    bfs_click(enqueue, mini_app)

    # print(f"[BFS] root page={root_page.index}, clicks={len(root_page.click_locations)}")
    # # 把 root_page 推入队列 enqueue，然后进入 bfs_click()。
    # enqueue.append(root_page)
    # bfs_click(enqueue, mini_app)

def bfs_click(enqueue, mini_app):
    # 先从队列里取一个页面 root_page，调用一次 page_bfs_click
    root_page = enqueue.pop(0)
    target_page = page_bfs_click(root_page, mini_app, enqueue)
    while len(enqueue) > 0 or target_page is not None:
        while target_page is None:
            # 表示当前分支“走完/走不动”，就从队列再取下一个 target_page，
            if len(enqueue) > 0:
                target_page = enqueue.pop(0)
            else:
                target_page = None
                break
            # 调用 enter_target_page(target_page) 试图复现到那个页面
            enter_success, enter_page = mini_app.enter_target_page(target_page)
            # 失败就用 enter_page 作为替代继续跑
            if not enter_success:
                print("not enter_success")
                if enter_page is not None:
                    # enqueue.append(target_page)
                    target_page = enter_page
                    break
                # else:
                #     enqueue.append(target_page)
        if target_page is not None:
            target_page = page_bfs_click(target_page, mini_app, enqueue)
        else:
            break


def page_bfs_click(target_page: Page, mini_app: mini_app_auto.MiniAppAuto, enqueue: list) -> [Page]:
    # 1. 【新增】加载全局访问历史
    visited_elements = mini_app_utils.load_visited_elements()
    # -----------------------------------------------------------
    # 情况 A：单点点击 (通常是Root页或特殊页)
    # -----------------------------------------------------------
    if len(target_page.click_locations) == 1:
        click_x, click_y = target_page.click_locations[0][0], target_page.click_locations[0][1]
        meta = target_page.get_click_meta(click_x, click_y)
        if meta:
            tgt_text = meta.get("text","")
            tgt_bbox = meta.get("bbox",[click_x,click_y,0,0])
        else:
            tgt_text, tgt_bbox = "", [int(click_x), int(click_y), 0, 0]     

        # 2. 【新增】检查去重 (单点模式也检查一下)
        # 注意：如果文本为空，建议用坐标兜底，避免跳过所有无字图标
        # visit_key = f"{target_page.index}|{tgt_text}"
        visit_key = f"{tgt_text}"
        # 如果 key 在历史中，且文本不为空（防止误杀无文本按钮），则跳过
        # 或者你希望严格去重，连无文本的也跳过，就去掉 'and tgt_text'
        if (visit_key in visited_elements) and tgt_text:
            print(f"[BFS] Skip visited single-node: {tgt_text}")
            return None # 或者视情况处理
        # 执行点击
        t_click = adb_commands.adb_click(click_x, click_y, return_ts=True)
        print(f"[BFS] single-click at ({click_x},{click_y},{tgt_text})")
        # 3. 【新增】记录到全局历史
        # mini_app_utils.save_visited_element(target_page.index, tgt_text, (click_x, click_y))
        mini_app_utils.save_visited_element( tgt_text, (click_x, click_y))
        # 写入操作记录
        # time.sleep(0.5)
        mini_app_utils.write_last_opt(mini_app.opt_count)
        if target_page.click_index < len(target_page.click_locations):
            target_page.click_index += 1

        is_new_page, new_or_similar_page = mini_app.create_normal_page(0, target_page)
        mini_app_utils.write_page_text(mini_app.opt_count, new_or_similar_page.page_dump_str)
        mini_app_utils.append_opt_image_map(mini_app.opt_count, new_or_similar_page.index)
        # === 新增：记录点击事件（与上面相同，注意 click_index=cdx）=== 写入文本、映射；记录一次 _append_ui_action 证据。
        mini_app_utils._append_ui_action(
            opt_id=mini_app.opt_count,
            page_before=target_page.index,
            page_after=new_or_similar_page.index,
            click_xy=(click_x, click_y),
            click_index=0,
            screenshot_index=new_or_similar_page.index,
            target_text=tgt_text, target_bbox=tgt_bbox,
            ts=t_click, 
        )
        # ============================================================
        mini_app.opt_count += 1
        target_page = new_or_similar_page
        print(f"[BFS]single opt={mini_app.opt_count}, page={new_or_similar_page.index}, clicks={len(new_or_similar_page.click_locations)}，click_index=0, click=({click_x},{click_y},{tgt_text})")
        return target_page
    # 多点分支：对 click_locations[target_page.click_index ...] 逐个
    print(target_page.click_locations)
    for cdx in range(target_page.click_index, len(target_page.click_locations)):
        print(f"page={target_page.index},cdx={cdx}")
        click_x, click_y = target_page.click_locations[cdx][0], target_page.click_locations[cdx][1]
        meta = target_page.get_click_meta(click_x, click_y)
        if meta:
            tgt_text = meta.get("text","")
            tgt_bbox = meta.get("bbox",[click_x,click_y,0,0])
        else:
            tgt_text, tgt_bbox = "", [int(click_x), int(click_y), 0, 0]

        # 4. 【新增】核心去重逻辑
        # visit_key = f"{target_page.index}|{tgt_text}"
        visit_key = f"{tgt_text}"
        # 策略：如果已经点过，且文本不为空，则跳过
        # (如果 tgt_text 为空，通常是图标或图片，md5+空字符串很容易重复误判，建议先不跳过，或者改用坐标key)
        if (visit_key in visited_elements) and tgt_text:
            print(f"[BFS] 🚫 Skip visited element: '{tgt_text}'")
            # 更新当前页面的 click_index，避免死循环卡在这里
            if target_page.click_index < len(target_page.click_locations):
                target_page.click_index += 1
            continue # 跳过本次循环，看下一个点

        print(f"[BFS]多点分支 opt={mini_app.opt_count}, page={target_page.index}, click_index={cdx}, click=({click_x},{click_y},{tgt_text})")
        t_click = adb_commands.adb_click(click_x, click_y, return_ts=True)
        # 5. 【新增】点击成功，立即写入全局历史
        # mini_app_utils.save_visited_element(target_page.index, tgt_text, (click_x, click_y))
        mini_app_utils.save_visited_element( tgt_text, (click_x, click_y))
        # 更新本地内存中的 visited 集合，防止本轮循环内重复（虽然 for 循环本身不会重，但为了保险）
        visited_elements.add(visit_key)

        # 写入操作记录
        mini_app_utils.write_last_opt(mini_app.opt_count)
        if target_page.click_index < len(target_page.click_locations):
            target_page.click_index += 1
        # 截屏识别新页
        is_new_page, new_or_similar_page = mini_app.create_normal_page(cdx, target_page)
        mini_app_utils.write_page_text(mini_app.opt_count, new_or_similar_page.page_dump_str)
        mini_app_utils.append_opt_image_map(mini_app.opt_count, new_or_similar_page.index)

        # === 新增：记录点击事件（与上面相同，注意 click_index=cdx）=== 写入文本、映射；记录一次 _append_ui_action 证据。
        mini_app_utils._append_ui_action(
            opt_id=mini_app.opt_count,
            page_before=target_page.index,
            page_after=new_or_similar_page.index,
            click_xy=(click_x, click_y),
            click_index=cdx,
            screenshot_index=new_or_similar_page.index,
            target_text=tgt_text, target_bbox=tgt_bbox,
            ts=t_click, 
        )
        # ============================================================


        mini_app.opt_count += 1
        # 如果出现“页面变化/新页”，则：需要探索的新页 push 进队列（enqueue.append(...)）
        if mini_app.current_page_is_root(new_or_similar_page): 
            if cdx < len(target_page.click_locations) - 1:
                enqueue.append(new_or_similar_page) 
                
            return None
        if not mini_app.is_similar_page(new_or_similar_page, target_page): # 新页
            if is_new_page and len(new_or_similar_page.page_dump_str) > 0:
                enqueue.append(new_or_similar_page)
                print("appendB")
            
            # 点击后返回，尝试回退到 target_page
            print(f"[BFS] try back to page {target_page.index} from page {new_or_similar_page.index}")
            back_success, actual_back_page = mini_app.back(target_page, new_or_similar_page)
            # 如果没有返回到预期的页面，就决定下一步用哪个页继续跑。
            if not back_success:
                print("not back_success")
                if mini_app.current_page_is_root(actual_back_page):
                    if cdx < len(target_page.click_locations) - 1:
                        enqueue.append(target_page)
                        print("appendC")
                    return None
                else:
                    return actual_back_page
    mini_app.close_mini_app()
    # if not mini_app.current_page_is_root(None):
    #     mini_app.start_mini_app()
    # 返回“下一个要继续展开的页面”或者 None
    return None


def mini_app_test(app_package, mini_app_platform, mini_app_name, mobile_model):
    dfs_bfs_auto_run(app_package, mini_app_platform, mini_app_name, mobile_model)

# def run_login_dfs(mini_app: mini_app_auto.MiniAppAuto, root_page: Page):
#     import mini_app_dfs_login
#     """
#     登录 DFS 阶段：
#       1) 从 root_page 找“我的/个人中心”等 → profile_page
#       2) 从 profile_page 找“授权登录/登录入口”等 → login_entry_page
#       3) 从 login_entry_page 找“一键登录/手机号快捷登录”等 → login_done_page
#     任一步失败都不影响后续 BFS，只是提前退出 DFS。
#     """
#     cfg = mini_app_dfs_login.DFS_CFG
#     max_depth = cfg.get("max_depth", 3)

#     # Step1: profile
#     print("[DFS] STEP1: PROFILE")
#     step1 = mini_app_dfs_login._dfs_step_by_keywords(
#         mini_app,
#         root_page,
#         cfg["step_profile"]["keywords"],
#         cfg["step_profile"]["sentinels"],
#         max_depth=max_depth
#     )
#     if step1 is None:
#         print("[DFS] STEP1 failed, maybe already logged in or no profile tab. continue to BFS.")
#         return

#     # Step2: login entry
#     print("[DFS] STEP2: LOGIN ENTRY")
#     step2 = mini_app_dfs_login._dfs_step_by_keywords(
#         mini_app,
#         step1,
#         cfg["step_login_entry"]["keywords"],
#         cfg["step_login_entry"]["sentinels"],
#         max_depth=max_depth
#     )
#     if step2 is None:
#         print("[DFS] STEP2 failed, maybe already logged in or no explicit login entry.")
#         return

#     # Step3: one-tap
#     print("[DFS] STEP3: ONE-TAP LOGIN")
#     step3 =mini_app_dfs_login. _dfs_step_by_keywords(
#         mini_app,
#         step2,
#         cfg["step_onetap"]["keywords"],
#         cfg["step_onetap"]["sentinels"],
#         max_depth=max_depth
#     )
#     if step3 is None:
#         print("[DFS] STEP3 not found, maybe only SMS login or already logged in.")
#         return

#     print(f"[DFS] login dfs finished at page {step3.index}")
#     # 到这里为止，登录 DFS 的所有点击 / 截图 / 文本都已经进入证据链



import pathlib
def clear_mitm_replay():
    #删除目录下的所有文件以及文件夹
    p= pathlib.Path("G:\miniapp\XPOScope-main\MiniAppLog\mitmproxy")
    # for file in p.iterdir():
    #     if file.is_file() :
    #         os.remove(file)
    for child in p.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            import shutil
            shutil.rmtree(child)
    #删除G:\miniapp\XPOScope-main\MiniAppLog\replay_result下的文件
    p= pathlib.Path(config.MINI_APP_LOG + "replay_result")
    for file in p.iterdir():
        if file.is_file() :
            os.remove(file)

def clear_mitm_replay():
    #删除目录G:\miniapp\XPOScope-main\MiniAppLog\mitmproxy下的所有文件以及文件夹
    p= pathlib.Path(config.MITM_DIR)
    # for file in p.iterdir():
    #     if file.is_file() :
    #         os.remove(file)
    for child in p.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            import shutil
            shutil.rmtree(child)
    #删除G:\miniapp\XPOScope-main\MiniAppLog\replay_result下的文件
    p= pathlib.Path(config.MINI_APP_LOG + "replay_result")
    for file in p.iterdir():
        if file.is_file() :
            os.remove(file)
    
def clear_visited_elements():
    p = os.path.join(config.PAGE_TEXT_PATH, "visited_elements.json")
    if os.path.exists(p):
        os.remove(p)


def clear_ui_actions():
    p = os.path.join(config.PAGE_TEXT_PATH, "ui_actions.ndjson")
    if os.path.exists(p):
        os.remove(p)

def clear_ocr_json():
    # 删除 ocr_raw_*.json 和 ocr_*.json 文件

    # p = os.path.join(config.PAGE_TEXT_PATH, "")
    p= pathlib.Path(config.PAGE_TEXT_PATH)
    for file in p.iterdir():
        if file.is_file() and (file.name.startswith("ocr_raw_") or file.name.startswith("ocr_") or file.name.startswith("ocr_llm_")) and file.suffix == ".json":
            os.remove(file)
    # if os.path.exists(p):
    #     os.remove(p)
if __name__ == "__main__":
    args = sys.argv
    mini_app_platform = int(args[1])
    mobile_model = int(args[2])
    mini_app_name = args[3].strip("'")
    # mini_app_platform = 0
    # mobile_model = 1
    # mini_app_name = 'SUPERHERO健身'
    if mini_app_platform == 0:
        app_package = 'com.eg.android.AlipayGphone'
    elif mini_app_platform == 1:
        app_package = 'com.tencent.mm'
    else:
        app_package = 'com.baidu.searchbox'
    
    mini_app_utils.del_evaluate_img()
    mini_app_utils.del_page_text()
    mini_app_utils.create_opt_file()
    mini_app_utils.create_opt_image_map_file()
    clear_ui_actions()
    clear_ocr_json()
    clear_mitm_replay()
    clear_visited_elements()
    mini_app_utils.remove_screenshot_img(mini_app_platform, config.MINI_APP_TYPE, mini_app_name)
    # eventlet.monkey_patch()
    with eventlet.Timeout(config.MINI_APP_TEST_TIME, False):
        print("Dynamic Exerciser start")

        mini_app_test(app_package, mini_app_platform, mini_app_name, mobile_model)
    # mini_app_utils.remove_screenshot_img(mini_app_platform, config.MINI_APP_TYPE, mini_app_name)
    print("Dynamic Exerciser end")
