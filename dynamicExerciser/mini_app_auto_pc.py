# dynamicExerciser/mini_app_auto_pc.py
import json
import os
import time
import config
import pc_commands as adb_commands
import mini_app_utils_pc as mini_app_utils
from page_utils.Page import Page
from page_utils.PageGraph import PageGraph
import sys
sys.path.append(r'G:\miniapp\XPOScope-main')
from OcrDump import ocr_recognition_pc as ocr_recognition
import target_resolver
# （可选）如果你能连上 DevTools，这里提供点击点与文本的增强
def devtools_click_candidates() -> list[list[int]]:
    # 返回 [[x,y], ...] 相对坐标（以 config.DEVICE_WIDTH/HEIGHT 为基准）
    return []

class MiniAppAuto:
    """PC 版：接口与安卓 MiniAppAuto 完全一致"""
    app_package = None
    mini_app_plat = None
    mini_app_name = None
    mobile_model = None
    d = None
    page_index = None
    root_page = None
    page_graph = None
    opt_count = None
    yolo_test = None
    login_dfs_clicks = None
    login_dfs_click_budget= None

    def __init__(self, app_package, mini_app_plat, mini_app_name, mobile_model):
        self.app_package = app_package
        self.mini_app_plat = mini_app_plat
        self.mini_app_name = mini_app_name
        self.mobile_model = mobile_model
        # PC: 初始化窗口与尺寸
        adb_commands._ensure_wechat()
        adb_commands.init_device_wh()
        self.page_index = 0
        self.opt_count = 0
        self.page_graph = PageGraph()

        self.yolo_test = None
        self.login_dfs_clicks = 0
        self.login_dfs_click_budget = getattr(config, "LOGIN_DFS_CLICK_BUDGET", 10)
            # print(traceback.format_exc())

        # self.yolo_test = evaluate.YoloTest()  # 保留对象以兼容 extract_image_info 调用

    def start_mini_app(self) -> Page:
        root_page = None
        self.clear_background_apps()
        config.operate_sleep()
        if self.mini_app_plat == 1:
            root_page = self.start_wx_mini_app()
            print("小程序已启动")
        elif self.mini_app_plat == 0:
            root_page = self.start_alipay_mini_app()
        elif self.mini_app_plat == 2:
            root_page = self.start_baidu_mini_app()
        if self.root_page is None:
            self.root_page = root_page
            self.page_graph.set_root_page(self.root_page)
        return self.root_page
    
    def start_wx_mini_app(self):
        time.sleep(3)
        mini_win,ts=adb_commands.open_miniprogram(self.mini_app_name)
        # adb_commands.set_always_on_top(True)
        if mini_win!=None:
            # run_pipeline=mini_app_login_pc.MiniAppLogin(mini_win)
            # cfg=""
            # cfg = mini_app_login_pc.load_cfg(cfg)
            # mini_app_login_pc.run_pipeline(mini_win,cfg)
            # print("自动登录成功，下面自由探索")

            # 拍根页并建 Page（与原逻辑一致）
            start_x, start_y = int(0.5 * config.DEVICE_WIDTH), int(0.25 * config.DEVICE_HEIGHT)
            root_page = self.create_root_page([start_x, start_y])
            mini_app_utils._append_ui_action(
                opt_id=999999,          # 建议 0
                page_before=None,
                page_after=root_page.index,                # root_page建好后也可以再补一次 page_after=root_page.index
                click_xy=(0, 0),
                click_index=-100,               # 用负数表示“非点击动作”
                screenshot_index= root_page.index,
                target_text="OPEN_MINIAPP",
                target_bbox=[0,0,0,0],
                ts=ts
            )
            return root_page

    # 支付宝/百度（可先留空或共用 wx 流程）
    def start_alipay_mini_app(self):
        return self.start_wx_mini_app()

    def start_baidu_mini_app(self):
        return self.start_wx_mini_app()

    def current_page_is_root(self, current_page):
        if self.root_page is None:
            return False
        if current_page is not None:
            return mini_app_utils.is_similar_page(current_page, self.root_page)
        current_dump_str, current_md5, _ = ocr_recognition.cache_image_dump_str()
        root_dump_str, root_md5 = self.root_page.page_dump_str, self.root_page.page_md5
        return mini_app_utils.is_similar_page_by_details(current_md5, current_dump_str, root_md5, root_dump_str)

    # def create_root_page(self, new_click_location):
    #     adb_commands.adb_screenshot(self.page_index)
    #     page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(0, False)
    #     root_page = Page(self.page_index, page_md5, page_dump_str)
    #     root_page.append_new_click_location(new_click_location)
    #     self.page_index += 1
    #     return root_page
    # dynamicExerciser/mini_app_auto_pc.py
    def create_root_page(self, new_click_location):
        adb_commands.adb_screenshot(self.page_index)
        # ★ 要 True 才会返回 ocr_click_locations
        from OcrDump import ocr_recognition_pc as ocr_recognition
        page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(self.page_index, True)
        root_page = Page(self.page_index, page_md5, page_dump_str)
        # 2) 调 LLM 生成可交互控件（优先）
        import pathlib
        try:
            import strategy.screenshot_to_llm as screenshot_to_llm
            ocr_json_path = str(pathlib.Path(config.PAGE_TEXT_PATH) / f"ocr_raw_{self.page_index}.json")
            img_path      = str(pathlib.Path(config.SCREENSHOT_PATH) / f"{self.page_index}.png")
            print("[ROOT] ocr_json_path =", ocr_json_path)
            print("[ROOT] img_path      =", img_path)

            interactive_elements = screenshot_to_llm.call_qwen_vl_for_interactive_elements(img_path, ocr_json_path )
            json_ocr_llm_file_path = os.path.join(config.PAGE_TEXT_PATH, f"ocr_llm_{self.page_index}.json")

            with open(json_ocr_llm_file_path, "w", encoding="utf-8") as f:
                json.dump(interactive_elements, f, ensure_ascii=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ROOT] ❌ llm 提取可交互控件失败: {repr(e)}")
        # 3) 从 LLM 结果 / OCR JSON 绑定 meta & 生成点击点
        click_hits = []
        try:
            p_llm = os.path.join(config.PAGE_TEXT_PATH, f"ocr_llm_{self.page_index}.json")
            if os.path.exists(p_llm):
                click_hits = json.load(open(p_llm, "r", encoding="utf-8"))
            else:
                raise FileNotFoundError(p_llm)
        except Exception:
            # LLM 没有 / 失败时兜底用 OCR raw
            try:
                p_raw = os.path.join(config.PAGE_TEXT_PATH, f"ocr_sorted_{self.page_index}.json")
                click_hits = json.load(open(p_raw, "r", encoding="utf-8"))
            except Exception as e2:
                print(f"[ROOT] ⚠️ 无法读取 ocr_llm / ocr_sorted: {repr(e2)}")
                click_hits = []

        click_locations_from_hits = []

        for it in (click_hits or []):
            cx, cy = it.get("click_xy", [None, None])
            # 如果没有 click_xy，用 bbox 算中心
            if cx is None or cy is None:
                bbox = it.get("bbox", None)
                if bbox and len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
            if cx is None or cy is None:
                continue

            root_page.register_click_meta(
                cx, cy,
                text=it.get("text", ""),
                bbox=it.get("bbox", [int(cx), int(cy), 0, 0]),
            )
            click_locations_from_hits.append([int(cx), int(cy)])

        # 4) 决定最终用于 BFS/DFS 的点击点来源
        if click_locations_from_hits:
            # ✅ 优先使用 LLM（或 OCR JSON）筛过的点
            root_page.append_new_click_locations(click_locations_from_hits)
        elif ocr_click_locations:
            # ⚠️ LLM / JSON 全部失败才用 dump_str 的 ocr_click_locations
            print("[ROOT] ⚠️ LLM / OCR JSON 均无有效点击点，fallback 使用 OCR dump_str 的 ocr_click_locations")
            for xy in ocr_click_locations:
                root_page.append_new_click_location(xy)
        else:
            # 实在啥都没有就用你给的兜底点（屏幕中上）
            root_page.append_new_click_location(new_click_location)
        print("[ROOT] 根页点击点：", root_page.click_locations)
        self.page_index += 1
        return root_page

    def create_normal_page(self, click_index, from_page: Page):
        if from_page.page_md5 == self.root_page.page_md5:
            config.short_sleep()
        config.short_sleep()
        temp_index = "temp"
        # 用 temp_index="temp" 截屏 → screenshot_dump_str("temp", True) 做 OCR，得到 page_dump_str / ocr_click_locations；
        adb_commands.adb_screenshot(temp_index)
        page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(temp_index, True)

        # 权限弹窗兜底（PC 常见“允许/继续/同意”）
        if self.contain_permission_tip(page_dump_str):
            adb_commands.adb_screenshot(temp_index)
            page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(temp_index, True)
        # 新页节点判重；若是“新页”，给它分配正式 index
        new_page = Page(temp_index, page_md5, page_dump_str)
        is_new_page, new_or_similar_page = self.page_graph.append_new_page_node(from_page, click_index, new_page)
        if is_new_page:
            new_page.set_index(self.page_index)
            adb_commands.rename_screenshot(temp_index, self.page_index)
            adb_commands._rename_temp_ocr_jsons_to_index(self.page_index)
            print("改名截图及OCR文件到index:", self.page_index)
            import strategy.screenshot_to_llm as screenshot_to_llm
            try:
                import time, pathlib, shutil
                ocr_json_path = str(pathlib.Path(config.PAGE_TEXT_PATH) / f"ocr_raw_{self.page_index}.json")
                img_path      = str(pathlib.Path(config.SCREENSHOT_PATH) / f"{self.page_index}.png")
                print(ocr_json_path)
                print(img_path)
                interactive_elements = screenshot_to_llm.call_qwen_vl_for_interactive_elements(img_path,ocr_json_path ) 
                json_ocr_llm_file_path = config.PAGE_TEXT_PATH + "ocr_llm_"+ str(self.page_index) + ".json"
                with open(json_ocr_llm_file_path, 'w', encoding='utf-8') as f:
                    json.dump(interactive_elements, f, ensure_ascii=False)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"❌ llm 提取可交互控件失败: {repr(e)}")
            
            # —— 从 ocr_{index}.json 绑定 meta ——
            try:
                # 如果ocr_llm_{self.page_index}.json不为空
                # import json, os
                p = os.path.join(config.PAGE_TEXT_PATH,f"ocr_llm_{self.page_index}.json")
                click_hits = json.load(open(p,"r",encoding="utf-8"))
            except Exception:
                p = os.path.join(config.PAGE_TEXT_PATH, f"ocr_sorted_{self.page_index}.json")
                click_hits = json.load(open(p,"r",encoding="utf-8"))

            # ===== 3) 从 click_hits 里注册 meta & 收集点击坐标 =====
            click_locations_from_hits = []
            for it in (click_hits or []):
                cx, cy = it.get("click_xy", [None, None])
                # 如果没有 click_xy，就用 bbox 算中心
                if cx is None or cy is None:
                    bbox = it.get("bbox", None)
                    if bbox and len(bbox) == 4:
                        x1, y1, x2, y2 = bbox
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2
                if cx is None or cy is None:
                    continue
                new_page.register_click_meta(cx, cy,text=it.get("text", ""),bbox=it.get("bbox", [int(cx), int(cy), 0, 0]),
                                            # score=it.get("score",0.0), source="ocr"
                )
                click_locations_from_hits.append([int(cx), int(cy)])
            # ===== 4) 决定最终用于 BFS 的点击点来源 =====
            if click_locations_from_hits:
                new_page.append_new_click_locations(click_locations_from_hits)
            else:
                print("⚠️ LLM + OCR JSON 都没有有效 click_xy，fallback 使用 OCR dump_str 的 ocr_click_locations")
                new_page.append_new_click_locations(ocr_click_locations)

            print(click_locations_from_hits)
            self.page_index += 1
        else:
            adb_commands.del_screenshot(temp_index)
        return is_new_page, new_or_similar_page

    def create_alone_page(self):
        config.short_sleep()
        temp_index = "temp"
        adb_commands.adb_screenshot(temp_index)
        page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(temp_index, True)
        if self.contain_permission_tip(page_dump_str):
            adb_commands.adb_screenshot(temp_index)
            page_dump_str, page_md5, ocr_click_locations = ocr_recognition.screenshot_dump_str(temp_index, True)
        alone_page = Page(temp_index, page_md5, page_dump_str)
        is_alone_page, alone_or_similar_page = self.page_graph.append_alone_page_node(alone_page)
        if is_alone_page:
            alone_page.set_index(self.page_index)
            adb_commands.rename_screenshot(temp_index, self.page_index)
            adb_commands._rename_temp_ocr_jsons_to_index(self.page_index)

            import strategy.screenshot_to_llm as screenshot_to_llm
            try:
                import time, pathlib, shutil
                ocr_json_path = str(pathlib.Path(config.PAGE_TEXT_PATH) / f"ocr_raw_{self.page_index}.json")
                img_path      = str(pathlib.Path(config.SCREENSHOT_PATH) / f"{self.page_index}.png")
                interactive_elements = screenshot_to_llm.call_qwen_vl_for_interactive_elements(img_path,ocr_json_path ) 
                json_ocr_llm_file_path = config.PAGE_TEXT_PATH + "ocr_llm_"+ str(self.page_index) + ".json"
                with open(json_ocr_llm_file_path, 'w', encoding='utf-8') as f:
                    json.dump(interactive_elements, f, ensure_ascii=False)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"❌ llm 提取可交互控件失败: {repr(e)}")

            try:
                # 如果ocr_llm_{self.page_index}.json不为空
                p = os.path.join(config.PAGE_TEXT_PATH, f"ocr_llm_{self.page_index}.json")
                click_hits = json.load(open(p,"r",encoding="utf-8"))
            except Exception:
                p = os.path.join(config.PAGE_TEXT_PATH, f"ocr_sorted_{self.page_index}.json")
                click_hits = json.load(open(p,"r",encoding="utf-8"))

            # ===== 3) 从 click_hits 里注册 meta & 收集点击坐标 =====
            click_locations_from_hits = []
            for it in (click_hits or []):
                cx, cy = it.get("click_xy", [None, None])
                # 如果没有 click_xy，就用 bbox 算中心
                if cx is None or cy is None:
                    bbox = it.get("bbox", None)
                    if bbox and len(bbox) == 4:
                        x1, y1, x2, y2 = bbox
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2
                if cx is None or cy is None:
                    continue
                alone_page.register_click_meta(cx, cy,text=it.get("text", ""),bbox=it.get("bbox", [int(cx), int(cy), 0, 0]),
                                            # score=it.get("score",0.0), source="ocr"
                )
                click_locations_from_hits.append([int(cx), int(cy)])
            # ===== 4) 决定最终用于 BFS 的点击点来源 =====
            if click_locations_from_hits:
                alone_page.append_new_click_locations(click_locations_from_hits)
            else:
                print("⚠️ LLM + OCR JSON 都没有有效 click_xy，fallback 使用 OCR dump_str 的 ocr_click_locations")
                alone_page.append_new_click_locations(ocr_click_locations)
                
            self.page_index += 1
        else:
            adb_commands.del_screenshot(temp_index)
        return is_alone_page, alone_or_similar_page

    def extract_click_locations(self, index):
        # 优先 DevTools（若可用）
        if self.yolo_test is None:
            return []
        dev = devtools_click_candidates()
        if dev:
            return dev
        # 兜底：沿用 YOLO 推断与 OCR 坐标（安卓版逻辑不变）
        screenshot_image_path = config.SCREENSHOT_PATH + str(index) + ".png"
        element_locations = mini_app_utils.extract_image_info(self.yolo_test, screenshot_image_path)
        if not element_locations:
            return []
        click_locations = []
        x_scale, y_scale = mini_app_utils.compute_xy_scale(index)  # 注意：要确保 compute_xy_scale 基于 PC 的 DEVICE_WIDTH/HEIGHT
        for (x1,y1,x2,y2) in element_locations:
            cx, cy = (x1+x2)/2, (y1+y2)/2
            real_x, real_y = x_scale*cx, y_scale*cy
            # if not mini_app_utils.is_noise_click_location(real_x, real_y):
            #     click_locations.append([int(real_x), int(real_y)])
            click_locations.append([int(real_x), int(real_y)])
        return click_locations

    @staticmethod
    def is_yolo_predict_success(dump_strs, element_num):
        word_num = sum(len(s) for s in dump_strs)
        return False if word_num / config.WORD_PER_ELEMENT > 1.5 * element_num else True

    # PC 清后台：NO-OP
    def clear_background_apps(self):
        pass

    # 权限/同意弹窗（按钮一般在底部）
    @staticmethod
    def contain_permission_tip(dump_strs):
        if mini_app_utils.contain_permission_tip(dump_strs):
            enter_x, enter_y = 0.75, 0.90
            adb_commands.adb_click_sleep(enter_x * config.DEVICE_WIDTH, enter_y * config.DEVICE_HEIGHT)

            return True
        return False

    def back(self, expect_back_page: Page, current_page: Page) -> [bool, Page]:
        """
        多策略回退：
        1) 键盘：Esc → Alt+Left → Backspace
        2) 标题栏返回热区
        3) OCR 文案返回
        4) 兜底：回根页并重放路径
        每次动作后都截屏建页，判断是否回到了期望页 / 至少不是当前页。
        """
        def snapshot_and_record(action_text: str):
            # 记录一次“回退”动作到证据链
            ts = time.time()
            is_alone_page, actual = self.create_alone_page()
            mini_app_utils._append_ui_action(
                opt_id=self.opt_count,
                page_before=(current_page.index if current_page else None),
                page_after=actual.index,
                click_xy=(0, 0),
                click_index=-1,
                screenshot_index=actual.index,
                target_text=action_text, target_bbox=[0,0,0,0],
                ts=ts
            )
            mini_app_utils.write_page_text(self.opt_count, actual.page_dump_str)
            mini_app_utils.append_opt_image_map(self.opt_count, actual.index)
            self.opt_count += 1
            return actual

        # 1) 键盘回退序列
        # adb_commands.adb_key_event(adb_commands.KEYCODE_BACK)
        # config.short_sleep()
        # actual = snapshot_and_record("BACK(KeySeq)")
        # if not mini_app_utils.is_similar_page(current_page, actual):
        #     return (mini_app_utils.is_similar_page(expect_back_page, actual), 
        #             expect_back_page if mini_app_utils.is_similar_page(expect_back_page, actual) else actual)

        # 2) 标题栏返回热区
        adb_commands.click_header_back_hotzone()
        config.short_sleep()
        actual = snapshot_and_record("BACK(HeaderHotzone)")
        if not mini_app_utils.is_similar_page(current_page, actual):
            return (mini_app_utils.is_similar_page(expect_back_page, actual), 
                    expect_back_page if mini_app_utils.is_similar_page(expect_back_page, actual) else actual)

        # 3) OCR 文字返回
        if ocr_recognition.try_ocr_back_click():
            config.short_sleep()
            actual = snapshot_and_record("BACK(OCR)")
            if not mini_app_utils.is_similar_page(current_page, actual):
                return (mini_app_utils.is_similar_page(expect_back_page, actual), 
                        expect_back_page if mini_app_utils.is_similar_page(expect_back_page, actual) else actual)

        # 4) 兜底：回根页并重放路径
        #    a) 重新打开小程序回到 Root
        # print("回退失败，尝试重启小程序回到根页")
        # adb_commands.restart_miniprogram(self.mini_app_name)
        # adb_commands.open_miniprogram(self.mini_app_name)
        # config.short_sleep()
        is_root_new, root_page = self.create_alone_page()
        mini_app_utils.write_page_text(self.opt_count, root_page.page_dump_str)
        mini_app_utils.append_opt_image_map(self.opt_count, root_page.index)
        self.opt_count += 1
        # 如果“重启后页面”和期望回退页很相似，就当作回退成功
        if mini_app_utils.is_similar_page(expect_back_page, root_page):
            return True, expect_back_page

        # 否则视为回退失败，但仍把当前 root_page 返回给上层，让上层自己决定怎么处理
        return False, root_page

    def enter_target_page(self, to_page: Page):
        enter_success = True

        # —— 1) 拿到根节点与目标节点
        parent_page = getattr(self, "root_page", None)
        if parent_page is None:
            # 没有 parent_page 说明状态不完整；返回失败更安全
            return not enter_success, None

        from_page_node = self.page_graph.root_page_node
        to_page_node   = self.page_graph.find_target_page_node(to_page)
        if from_page_node is None or to_page_node is None:
            return not enter_success, None
        if from_page_node.page.page_md5 == to_page_node.page.page_md5:
            return enter_success, None

        click_operations_list = self.page_graph.get_click_operations_list(from_page_node, to_page_node)
        if not click_operations_list:
            return not enter_success, None

        # —— 2) 第一次点击：以 root_page 为“点击前页”上下文
        root_click_x, root_click_y = parent_page.click_locations[0]
        meta = parent_page.get_click_meta(root_click_x, root_click_y)
        if meta:
            tgt_text = meta.get("text","")
            tgt_bbox = meta.get("bbox",[root_click_x, root_click_y,0,0])
        else:
            tgt_text, tgt_bbox = "", [int(root_click_x), int(root_click_y), 0, 0]

        # 真正点击（取同一时刻 ts）
        ts_click = adb_commands.adb_click(root_click_x, root_click_y, return_ts=True)

        mini_app_utils.write_last_opt(self.opt_count)
        config.short_sleep()

        # 点击后构建/比对页面（仍按你的原逻辑）
        is_new_page, new_or_similar_page = self.create_normal_page(0, parent_page)
        mini_app_utils.write_page_text(self.opt_count, new_or_similar_page.page_dump_str)
        mini_app_utils.append_opt_image_map(self.opt_count, new_or_similar_page.index)

        # 记录 UI 动作（第一次点击）
        try:
            mini_app_utils._append_ui_action(
                opt_id=self.opt_count,
                page_before=parent_page.index,
                page_after=new_or_similar_page.index,
                click_xy=(root_click_x, root_click_y),
                click_index=0,
                screenshot_index=new_or_similar_page.index,
                target_text=tgt_text,
                target_bbox=tgt_bbox,
                ts=ts_click
            )
        except Exception as e:
            print(f"[UI-ACTION] write failed: {e}")

        self.opt_count += 1

        # 若一次点击就到目标，按你原来的语义返回
        if is_new_page:
            return not enter_success, new_or_similar_page

        # —— 3) 多步点击路径（保留你原判断，但修正 parent/context 的使用）
        # click_operations_list 是若干“路径”，挑与 new_or_similar_page 对齐的那条
        for click_ops in click_operations_list:
            if len(click_ops) > 1 and click_ops[1].page_md5 == new_or_similar_page.page_md5:
                # 当前用于 OCR 的“上下文页”（点击前页）
                ctx_page = new_or_similar_page

                for idx in range(1, len(click_ops)):
                    cx, cy = click_ops[idx].click_x, click_ops[idx].click_y
                    meta = ctx_page.get_click_meta(cx, cy)
                    if meta:
                        tgt_text = meta.get("text","")
                        tgt_bbox = meta.get("bbox",[cx, cy,0,0])
                    else:
                        tgt_text, tgt_bbox = "", [int(cx), int(cy), 0, 0]

                    ts_click = adb_commands.adb_click(cx, cy, return_ts=True)
                    mini_app_utils.write_last_opt(self.opt_count)
                    time.sleep(1)

                    if idx == len(click_ops) - 1:
                        # —— 最后一击：真正跳页
                        click_index = click_ops[idx].click_index
                        parent_page2 = self.page_graph.get_page_by_md5(click_ops[idx].page_md5)
                        if parent_page2 is None:
                            is_alone_page, curr_page = self.create_alone_page()
                        else:
                            is_new_page2, curr_page = self.create_normal_page(click_index, parent_page2)

                        mini_app_utils.write_page_text(self.opt_count, curr_page.page_dump_str)
                        mini_app_utils.append_opt_image_map(self.opt_count, curr_page.index)

                        # 记录 UI 动作（最后一步）
                        try:
                            mini_app_utils._append_ui_action(
                                opt_id=self.opt_count,
                                page_before=getattr(ctx_page, "index", None),           # 点击前页的截图
                                page_after=curr_page.index,
                                click_xy=(cx, cy),
                                click_index=click_ops[idx].click_index,
                                screenshot_index=curr_page.index,
                                target_text=tgt_text,
                                target_bbox=tgt_bbox,
                                ts=ts_click
                            )
                        except Exception as e:
                            print(f"[UI-ACTION] write failed: {e}")

                        self.opt_count += 1

                        # 更新当前根页供下次 BFS
                        self.root_page  = curr_page
                        self.page_index = getattr(curr_page, "index", self.page_index)

                        if mini_app_utils.is_similar_page(to_page, curr_page):
                            return enter_success, None
                        else:
                            return not enter_success, curr_page
                    else:
                        # —— 中间步骤：可能只是弹层/状态变化，先做缓存文本与“临时截图”索引
                        from OcrDump import ocr_recognition_pc as ocr_recognition
                        dump_str, md5, _ = ocr_recognition.cache_image_dump_str()
                        mini_app_utils.write_page_text(self.opt_count, dump_str)
                        mini_app_utils.append_opt_image_map(self.opt_count, "temp")

                        # 记录 UI 动作（中间步，page_after 暂时未知，用 None）
                        try:
                            mini_app_utils._append_ui_action(
                                opt_id=self.opt_count,
                                page_before=getattr(ctx_page, "index", None),
                                page_after=None,
                                click_xy=(cx, cy),
                                click_index=click_ops[idx].click_index,
                                screenshot_index="temp",
                                target_text=tgt_text,
                                target_bbox=tgt_bbox,
                                ts=ts_click
                            )
                        except Exception as e:
                            print(f"[UI-ACTION] write failed: {e}")

                        self.opt_count += 1

                        # 上下文页**通常不变**（仍是点击前的那页）；
                        # 如你的 create_* 系列能识别中间页，可在这里更新 ctx_page = 中间页
                        # 现在保持不变更稳妥
                break  # 找到匹配路径就退出

        # 路径不匹配或未返回，按失败处理
        return not enter_success, None


    def close_mini_app(self):
        # PC：一般左上角“←”或 Esc，保持与安卓相同接口
        adb_commands.adb_key_event(adb_commands.KEYCODE_BACK)
        
    @staticmethod
    def is_similar_page(page1: Page, page2: Page):
        return mini_app_utils.is_similar_page(page1, page2)
    
    @staticmethod
    def wx_contain_permission_tip(dump_strs):
        device_width, device_height = config.DEVICE_WIDTH, config.DEVICE_HEIGHT
        if mini_app_utils.contain_permission_tip(dump_strs):
            enter_x, enter_y = 0.7, 0.9
            adb_commands.adb_click_sleep(enter_x * device_width, enter_y * device_height)
            return True
        else:
            return False

