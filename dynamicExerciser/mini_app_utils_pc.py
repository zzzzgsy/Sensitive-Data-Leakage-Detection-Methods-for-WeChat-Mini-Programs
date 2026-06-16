import json
import random
import re
import shutil

# import uiautomator2 as u2
import os
import time
import config
import mini_app_auto_pc as mini_app_auto
from page_utils.Page import Page
from PIL import Image
# 定义一个全局去重文件路径
VISITED_LOG_PATH = config.PAGE_TEXT_PATH + "visited_elements.json"

def load_visited_elements():
    if not os.path.exists(VISITED_LOG_PATH):
        return set()
    try:
        with open(VISITED_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data)
    except:
        return set()

def save_visited_element(index, text, xy=None):
    # 生成唯一 key，例如 "MD5|TEXT" 或者粗略坐标
    # 建议使用 MD5 + Text，因为坐标可能会微变
    key = f"{text}"
    
    current = load_visited_elements()
    if key not in current:
        current.add(key)
        with open(VISITED_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(list(current), f, ensure_ascii=False)
            
def _append_ui_action(opt_id, page_before, page_after, click_xy, click_index, screenshot_index,
                      target_text=None, target_bbox=None,ts=None):
    """
    将一次点击动作落盘到 PAGE_TEXT_PATH/ui_actions.ndjson
    """
    try:
        # ts = time.time()
        ts_val = float(ts) if ts is not None else time.time()
        rec = {
            "evt": "ui_action",
            "opt_id": int(opt_id),
            "ts": ts_val,
            "page_before": int(page_before) if page_before is not None else None,
            "page_after": int(page_after) if page_after is not None else None,
            "click_index": int(click_index) if click_index is not None else None,
            "click_xy": [int(click_xy[0]), int(click_xy[1])],
            "target": {
                "text": target_text or "",
                "bbox": target_bbox or [int(click_xy[0]), int(click_xy[1]), 0, 0]  # 没有宽高先填 0
            },
            "screenshot_index": str(screenshot_index) if screenshot_index is not None else None
        }
        out_dir = config.PAGE_TEXT_PATH
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "ui_actions.ndjson")
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[UI-ACTION] write failed: {e}")


# def connect_device():
#     d = u2.connect(get_device_serial())
#     return d


def get_device_serial():
    cmd_res = os.popen("adb devices").readlines()
    device_serial = cmd_res[1].split('\t')[0]
    return device_serial


def list_similarity_check(list1: list, list2: list):
    same_count = 0
    for val in list1:
        if val in list2:
            same_count += 1
    max_len = len(list1) if len(list1) >= len(list2) else len(list2)
    if len(list1) <= 5 and len(list2) <= 5:
        if same_count > 1:
            return True
        else:
            return False

    if len(list1) > 10 and len(list2) > 10:
        if max_len * config.SIMILAR_THRESHOLD <= same_count:
            return True
        else:
            return False
    else:
        if max_len * 0.5 <= same_count:
            return True
        else:
            return False
# def list_similarity_check(list1: list, list2: list):
#     if not list1 or not list2:
#         return False
#     s1, s2 = set(list1), set(list2)
#     jacc = len(s1 & s2) / max(1, len(s1 | s2))
#     # 用 Jaccard，阈值可配；root 判同用更高阈值（如 0.6）
#     return jacc >= getattr(config, "PAGE_SIMILARITY_JACCARD", 0.5)



def is_similar_page(page1: Page, page2: Page):
    return is_similar_page_by_details(page1.page_md5, page1.page_dump_str, page2.page_md5, page2.page_dump_str)


# def is_similar_page_by_details(page1_md5, page1_dump_str, page2_md5, page2_dump_str):
#     if page1_md5 is None or page2_md5 is None or page1_dump_str is None or page2_dump_str is None:
#         return False
#     if page1_md5 == page2_md5 or list_similarity_check(page1_dump_str, page2_dump_str):
#         return True
#     return False
import imagehash

def is_similar_page_by_details(page1_phash, page1_dump_str, page2_phash, page2_dump_str):
    if page1_phash is None or page2_phash is None or page1_dump_str is None or page2_dump_str is None:
        return False
        
    # 第一重校验：宏观视觉感知哈希（计算汉明距离）
    try:
        hash1 = imagehash.hex_to_hash(page1_phash)
        hash2 = imagehash.hex_to_hash(page2_phash)
        hamming_distance = hash1 - hash2
    except Exception:
        return False
        
    # 如果视觉差异过大（汉明距离 > 23），直接判定为不同页面
    # 23 是工程上常用的经验阈值，容忍了光标闪烁、轮播图部分切换等微小扰动
    if hamming_distance > 23:
        return False

    # 第二重校验：视觉相似的情况下，精准比对文本（论文中的 Jaccard 公式）
    # page_dump_str 本身就是 OCR 提取出的文本列表 (list)
    set1 = set(page1_dump_str)
    set2 = set(page2_dump_str)
    
    # 避免空集导致除零异常
    if not set1 and not set2:
        return True
    if not set1 or not set2:
        return False
        
    # 严格按照 Jaccard = 交集长度 / 并集长度
    jaccard_sim = len(set1.intersection(set2)) / len(set1.union(set2))
    
    # 对应论文中的 theta = 0.8
    if jaccard_sim > 0.8:
        return True
        
    # 视觉相似但文本差异大（如复用UI模板的新业务页面）
    return False



def extract_image_info(yolo_test, image_path) -> list:
    if yolo_test is None:
        return []
    all_element_list = yolo_test.predictOneImg(image_path)
    location_lists = []
    for element_list in all_element_list:
        location = []
        if len(element_list) > 4:
            for index in range(4):
                location.append(element_list[index])
        if location not in location_lists:
            location_lists.append(location)
    return location_lists

YOLO_REF_W, YOLO_REF_H = 720, 1280  # YOLO 输入尺寸
def compute_xy_scale(index):
    screenshot_path = config.SCREENSHOT_PATH + str(index) + ".png"
    evaluate_path = config.EVALUATE_PATH + str(index) + ".png"
    screenshot_img = Image.open(screenshot_path)
    sw, sh = screenshot_img.width, screenshot_img.height

    # evaluate_img = Image.open(evaluate_path)
    if os.path.exists(evaluate_path):
        evaluate_img = Image.open(evaluate_path)
        ew, eh = evaluate_img.width, evaluate_img.height
    else:
        ew, eh = YOLO_REF_W, YOLO_REF_H  # ★ 无 evaluate 图时的兜底

        # 避免 0 除
    ew = ew or YOLO_REF_W
    eh = eh or YOLO_REF_H

    return sw / ew, sh / eh

    # screenshot_width, screenshot_height = screenshot_img.width, screenshot_img.height
    # evaluate_width, evaluate_height = evaluate_img.width, evaluate_img.height
    # return screenshot_width / evaluate_width, screenshot_height / evaluate_height


def is_noise_click_location(x, y):
    bound_left, bound_right, bound_top, bound_bottom = 0, config.DEVICE_WIDTH, 0, 0.09 * config.DEVICE_HEIGHT
    if bound_left <= x <= bound_right and bound_top <= y < bound_bottom:
        return True
    return False




def random_click_location(now_click_locations):
    device_width, device_height = config.DEVICE_WIDTH, config.DEVICE_HEIGHT
    while True:
        x = random.randint(0, device_width)
        y = random.randint(0, device_height)
        # if not is_noise_click_location(x, y) and [x, y] not in now_click_locations:
        #     return [x, y]
        return [x, y]


agree_list = {"允许", "同意"}
deny_list = {"拒绝", "取消"}
tip_list = {"授权", "申请", "权限", "获取"}


def contain_permission_tip(dump_strs):
    if not any_element_in_list(agree_list, dump_strs):
        return False
    if not any_element_in_list(deny_list, dump_strs):
        return False
    if not any_tip_in_list(tip_list, dump_strs):
        return False
    return True


def any_element_in_list(element_list, dump_strs):
    for element in element_list:
        if element in dump_strs:
            return True
    return False


def any_tip_in_list(element_list, dump_strs):
    for element in element_list:
        if contain_part_dump_str(dump_strs, element):
            return True
    return False


def contain_part_dump_str(dump_strs, target_str):
    for dump_str in dump_strs:
        if target_str in dump_str:
            return True
    return False


def create_opt_file():
    page_text_path = config.PAGE_TEXT_PATH + "opt.txt"
    if os.path.exists(page_text_path):
        os.remove(page_text_path)
    fp = open(config.PAGE_TEXT_PATH + "opt.txt", 'w')
    fp.close()


def create_opt_image_map_file():
    opt_image_map_path = config.PAGE_TEXT_PATH + "opt_image_map.txt"
    if os.path.exists(opt_image_map_path):
        os.remove(opt_image_map_path)
    fp = open(config.PAGE_TEXT_PATH + "opt_image_map.txt", "w")
    fp.close()


def write_last_opt(opt_count):
    opt_file_path = config.PAGE_TEXT_PATH + "opt.txt"
    with open(opt_file_path, 'w', encoding='utf-8') as f:
        f.write(str(opt_count))
        f.flush()
    f.close()


def append_opt_image_map(opt_count, image_index):
    opt_image_map_path = config.PAGE_TEXT_PATH + "opt_image_map.txt"
    with open(opt_image_map_path, 'a', encoding='utf-8') as f:
        f.write(str(opt_count) + " " + str(image_index) + "\n")
        f.flush()
    f.close()


def write_page_text(opt_page_count, dump_strs: list):
    page_file_path = config.PAGE_TEXT_PATH + str(opt_page_count) + ".txt"
    with open(page_file_path, 'w', encoding='utf-8') as f:
        for dump_str in dump_strs:
            f.write(dump_str + "\n")
        f.flush()
    f.close()
    if opt_page_count==0:
        # 复制文件0.txt到999999.txt
        shutil.copy(page_file_path, config.PAGE_TEXT_PATH + "999999.txt")


def read_page_text(opt_page_count):
    page_file_path = config.PAGE_TEXT_PATH + str(opt_page_count) + ".txt"
    res = []
    with open(page_file_path, 'r', encoding='utf-8') as f:
        dump_strs = f.readlines()
    f.close()

    for dump_str in dump_strs:
        new_str = re.sub('\n', "", dump_str)
        res.append(new_str)
    return res


def del_evaluate_img():
    for file in os.listdir(config.SCREENSHOT_PATH):
        source_file = os.path.join(config.SCREENSHOT_PATH, file)
        if os.path.isfile(source_file) and source_file.find(".png") > 0:
            os.remove(source_file)


def del_screenshot_img():
    for file in os.listdir(config.EVALUATE_PATH):
        source_file = os.path.join(config.EVALUATE_PATH, file)
        if os.path.isfile(source_file) and source_file.find(".png") > 0:
            os.remove(source_file)


def remove_screenshot_img(mini_app_plat, mini_app_type, mini_app_name):
    target_dir = config.SCREENSHOT_PATH
    if mini_app_plat == 0:
        target_dir += "alipay/"
    if mini_app_plat == 1:
        target_dir += "wechat/"
    if mini_app_plat == 2:
        target_dir += "baidu/"
    target_dir += mini_app_type + "/"
    target_dir += mini_app_name
    mkdir(target_dir)
    for file in os.listdir(config.SCREENSHOT_PATH):
        source_file = os.path.join(config.SCREENSHOT_PATH, file)
        target_file = os.path.join(target_dir, file)
        if os.path.isfile(source_file) and source_file.find(".png") > 0:
            shutil.move(source_file, target_file)


def del_page_text():
    for file in os.listdir(config.PAGE_TEXT_PATH):
        source_file = os.path.join(config.PAGE_TEXT_PATH, file)
        if os.path.isfile(source_file) and source_file.find(".txt") > 0:
            os.remove(source_file)


def mkdir(target_dir):
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)


if __name__ == "__main__":
    remove_screenshot_img(1, config.MINI_APP_TYPE, "test")
