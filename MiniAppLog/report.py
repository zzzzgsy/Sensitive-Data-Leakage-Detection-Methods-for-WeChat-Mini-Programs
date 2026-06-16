import json
import multiprocessing
import os
import time
import re
import socket
import threading
import eventlet
import config
from trafficMonitor import traffic_utils as traffic_utils
import xlrd
import urllib.parse as up
def _fmt_val(v, maxlen=120):
    """避免 value 太长撑爆文本，适度截断。"""
    s = str(v)
    return s if len(s) <= maxlen else (s[:maxlen] + "…")

def _iter_findings(raw):
    """
    统一把 finding 迭代为 {type:..., value:...} 形式。
    支持两种输入：[(type, value), ...] 或 [{"type":..,"value":..}, ...]
    """
    if not raw:
        return
    for it in raw:
        if isinstance(it, dict):
            t, v = it.get("type"), it.get("value")
        elif isinstance(it, (list, tuple)) and len(it) >= 2:
            t, v = it[0], it[1]
        else:
            continue
        if t is None or v is None or str(v) == "":
            continue
        yield {"type": t, "value": v}

def _write_inline_findings(tf, findings, indent="    "):
    """
    在 TXT 中把该条流量的 finding 逐条写在下一行：
        -- [finding] {type} {value}
    自动去重 + 截断 value。
    """
    if not findings:
        return
    seen = set()
    for fd in _iter_findings(findings):
        key = (fd["type"], str(fd["value"]))
        if key in seen:
            continue
        seen.add(key)
        tf.write(f"{indent}-- [finding] {fd['type']} {_fmt_val(fd['value'])}\n")

def _summarize_findings(findings_all, topn=10):
    """
    对单个 Action 的所有 finding 做一个简要“综合统计”字符串：
      形如：user_id×3, token×2, phone×1 ...
    """
    from collections import Counter
    counter = Counter(fd["type"] for fd in _iter_findings(findings_all))
    if not counter:
        return ""
    parts = [f"{t}×{n}" for t, n in counter.most_common(topn)]
    return ", ".join(parts)

def generate_opt_image_map():
    opt_image_map_path = config.PAGE_TEXT_PATH + "opt_image_map.txt"
    opt_image_map = {}
    with open(opt_image_map_path, 'r') as f:
        line = f.readline().replace('\n', '')
        while line:
            opt_image = line.split(' ')
            opt_count = opt_image[0]
            image_index = opt_image[1]
            opt_image_map[opt_count] = image_index
            line = f.readline().replace('\n', '')
    return opt_image_map


def read_page_text(page_index):
    page_file_path = config.PAGE_TEXT_PATH + str(page_index) + ".txt"
    res = []

    # 【新增】检查文件是否存在
    if not os.path.exists(page_file_path):
        # 如果文件不存在，直接返回空列表 res (即 [])，函数结束，不会报错
        return res

    # 文件存在才进行打开操作
    with open(page_file_path, 'r', encoding='utf-8') as f:
        dump_strs = f.readlines()
        # f.close() # 使用 with open 块会自动关闭文件，不需要手动调用 close()
        
    for dump_str in dump_strs:
        new_str = re.sub('\n', "", dump_str)
        res.append(new_str)
    return res


def _load_ui_actions():
    """从 PAGE_TEXT_PATH/ui_actions.ndjson 读取动作列表"""
    actions_path = os.path.join(config.PAGE_TEXT_PATH, "ui_actions.ndjson")
    acts = []
    if not os.path.exists(actions_path):
        return acts
    with open(actions_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                acts.append(rec)
            except json.JSONDecodeError:
                continue
    # 按时间排序
    acts.sort(key=lambda x: x.get("ts", 0.0))
    return acts

def _score_request(url, method, target_text):
    score = 0.0
    path = up.urlparse(url).path.lower()
    if "/api" in path or "/user" in path or "/wx" in path:
        score += 0.6
    if method == "POST":
        score += 0.3
    if target_text:
        for tok in target_text.lower().split():
            if tok and tok in path:
                score += 0.4
                break
    return round(score, 3)

def _split_reqresp_key(k: str):
    """
    'https://a/b#REQ#123' -> ('https://a/b', 'REQ', '123')
    'https://a/b#RESP#xyz'-> ('https://a/b', 'RESP', 'xyz')
    其它 -> (k, None, None)
    """
    if "#REQ#" in k:
        base, reqid = k.split("#REQ#", 1)
        return base, "REQ", reqid
    if "#RESP#" in k:
        base, reqid = k.split("#RESP#", 1)
        return base, "RESP", reqid
    return k, None, None

def generate_evidence_reports(mini_app_name, mini_app_plat, url_traffic_map, url_page_index_map, url_ts_map,
                              window_s=None, max_urls_per_action=10):
    if window_s is None:
        window_s = getattr(config, "EVIDENCE_WINDOW_S", 3.0)

    actions = _load_ui_actions()
    if not actions:
        print("[EVIDENCE] no ui_actions.ndjson found, skip.")
        return

    report_dir = config.MINI_APP_LOG
    if mini_app_plat == 0: report_dir += "alipay/"
    if mini_app_plat == 1: report_dir += "wechat/"
    if mini_app_plat == 2: report_dir += "baidu/"
    report_dir = os.path.join(report_dir, config.MINI_APP_TYPE)
    os.makedirs(report_dir, exist_ok=True)

    # txt_path  = os.path.join(report_dir, f"{mini_app_name}.evidence.txt")
    # jsonl_path= os.path.join(report_dir, f"{mini_app_name}.evidence.jsonl")
    txt_path  = report_dir + "/" + mini_app_name+ "evidence.txt"
    jsonl_path=  report_dir + "/" + mini_app_name+ "evidence.jsonl"
    opt_image_map = generate_opt_image_map()

    with open(txt_path, "w", encoding="utf-8") as tf, open(jsonl_path, "w", encoding="utf-8") as jf:
        for act in actions:
            opt_id = str(act.get("opt_id"))
            ts0 = float(act.get("ts", 0.0))
            pre_w  = getattr(config, "EVIDENCE_PRE_WINDOW_S", 2.0)
            post_w = getattr(config, "EVIDENCE_POST_WINDOW_S", 6.0)
            t_start, t_end = ts0 - pre_w, ts0 + post_w

            # 1) 找到该 opt 的所有“兼容 key”（携 req/resp 后缀）
            keys_same_opt = [k for k, page_idx in url_page_index_map.items() if str(page_idx) == opt_id]
            # 2) 时间窗口筛选
            cand = [(k, float(url_ts_map.get(k, 0.0))) for k in keys_same_opt
                    if t_start <= float(url_ts_map.get(k, 0.0)) <= t_end]
            fallback = False
            if not cand and keys_same_opt:
                cand = [(k, float(url_ts_map.get(k, 0.0))) for k in keys_same_opt]
                fallback = True

            # 3) 按 req_id 分组配对
            by_reqid = {}
            for k, ts in cand:
                base, kind, reqid = _split_reqresp_key(k)
                if not reqid:  # 非“兼容 key”的就以 URL 当 reqid 兜底
                    reqid = base
                    kind  = "UNK"
                g = by_reqid.setdefault(reqid, {"base": base, "ts": ts, "REQ": None, "RESP": None, "UNK": []})
                if kind in ("REQ","RESP"):
                    g[kind] = k
                else:
                    g["UNK"].append(k)
                # 取最早时间作组时间
                if ts and (g.get("ts") is None or ts < g["ts"]):
                    g["ts"] = ts

            # 4) 输出 Page
            img_idx = opt_image_map.get(opt_id, "temp")
            tf.write(f"Page {opt_id} {img_idx}\n")

            # 5) 输出 Action
            tgt = (act.get("target") or {})
            tgt_text = tgt.get("text", "")
            tgt_bbox = tgt.get("bbox", None)
            shot_idx = act.get("screenshot_index")
            shot_name = f"screen_{shot_idx}.png" if shot_idx and shot_idx != "temp" else None
            tf.write(
                f"[Action] click text='{tgt_text}' bbox={tgt_bbox} "
                f"screenshot={shot_name} ts={ts0} "
                f"page_before={act.get('page_before')} page_after={act.get('page_after')}\n"
            )

            # 6) 对每个 req_id 组做隐私提取并输出 Req/Resp 明细
            all_findings_pairs = []   # 收集结构化 finding，供“综合统计”
            json_items = []           # 用于 JSONL（保持你现有结构）

            for reqid, grp in sorted(by_reqid.items(), key=lambda x: x[1]["ts"] or 0.0):
                base = grp["base"]
                k_req, k_resp = grp["REQ"], grp["RESP"]
                ts_req  = url_ts_map.get(k_req)  if k_req  else None
                ts_resp = url_ts_map.get(k_resp) if k_resp else None

                # 取 payload
                pay_req  = url_traffic_map.get(k_req)  if k_req  else None
                pay_resp = url_traffic_map.get(k_resp) if k_resp else None

                # detect_privacy（逐条流量）
                f_req  = traffic_utils.detect_privacy(pay_req)  if pay_req  else []
                f_resp = traffic_utils.detect_privacy(pay_resp) if pay_resp else []

                # ---- 文本输出：先写 Req/Resp 行，再在下一行内联 finding ----
                if k_req:
                    tf.write(f"  - [Req]  {base} ts={ts_req} match={'time+page' if not fallback else 'page-only'}\n")
                    _write_inline_findings(tf, f_req, indent="    ")

                if k_resp:
                    tf.write(f"  - [Resp] {base} ts={ts_resp} match={'time+page' if not fallback else 'page-only'}\n")
                    _write_inline_findings(tf, f_resp, indent="    ")

                # ---- 汇总（用于你原来的 [Findings] 行和新增 [finding total]）----
                for fd in _iter_findings(f_req):
                    all_findings_pairs.append(fd)
                for fd in _iter_findings(f_resp):
                    all_findings_pairs.append(fd)

                # ---- JSONL（保持原样结构）----
                json_items.append({
                    "req_id": reqid,
                    "base_url": base,
                    "req": {
                        "ts": ts_req,
                        "privacy_findings": [{"type": fd["type"], "value": fd["value"]} for fd in _iter_findings(f_req)]
                    } if k_req else None,
                    "resp": {
                        "ts": ts_resp,
                        "privacy_findings": [{"type": fd["type"], "value": fd["value"]} for fd in _iter_findings(f_resp)]
                    } if k_resp else None,
                    "match": "time+page" if not fallback else "page-only"
                })

            # 旧的“平铺聚合”行（与历史兼容，保留）
            if all_findings_pairs:
                tf.write("[Findings] " + ",".join([f"{fd['type']} {fd['value']}" for fd in all_findings_pairs]) + "\n")


            # 7) UI 文本侧证据
            try:
                ui_text = read_page_text(int(opt_id))
                if ui_text:
                    tf.write("[UI Text] " + ",".join(ui_text) + "\n")
            except:
                pass
            
            
            # 7.1) 新增：‘综合统计’行（基于上面的 all_findings_pairs）
            sum_line = _summarize_findings(all_findings_pairs, topn=getattr(config, "EVIDENCE_FINDING_TOTAL_TOPN", 10))
            if sum_line:
                tf.write(f"[finding total] {sum_line}\n")

            tf.write("\n")
            # JSONL
            jf.write(json.dumps({
                "opt_id": int(opt_id),
                "ts_action": ts0,
                "page_before": act.get("page_before"),
                "page_after": act.get("page_after"),
                "click_index": act.get("click_index"),
                "click_xy": act.get("click_xy"),
                "screenshot_index": act.get("screenshot_index"),
                "target": {"text": tgt_text, "bbox": tgt_bbox},
                "requests": json_items
            }, ensure_ascii=False) + "\n")

    print(f"[EVIDENCE] written: {txt_path}")
    print(f"[EVIDENCE] written: {jsonl_path}")

def generate_report(mini_app_name, mini_app_plat, url_traffic_map, url_page_index_map):
    url_privacy_tuples_map = {}
    for url in url_traffic_map.keys():
        if url not in url_privacy_tuples_map.keys():
            traffic = url_traffic_map[url]
            privacy_traffic = traffic_utils.detect_privacy(traffic)
            if len(privacy_traffic) != 0:
                url_privacy_tuples_map[url] = privacy_traffic
    opt_urls_map = {}
    for url in url_page_index_map.keys():
        if url not in url_privacy_tuples_map.keys():
            continue
        page_index = url_page_index_map[url]
        if page_index not in opt_urls_map.keys():
            opt_urls_map[page_index] = [url]
        else:
            opt_urls_map[page_index].append(url)

    print("开始生成报告")
    report_path = config.MINI_APP_LOG
    if mini_app_plat == 0:
        report_path += "alipay/"
    if mini_app_plat == 1:
        report_path += "wechat/"
    if mini_app_plat == 2:
        report_path += "baidu/"
    report_path = report_path + config.MINI_APP_TYPE + "/" + mini_app_name + ".txt"
    if not os.path.exists(report_path):
        dir_path = os.path.dirname(report_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    opt_image_map = generate_opt_image_map()
    with open(report_path, 'w') as f:
        for opt_count in opt_urls_map.keys():
            if opt_count in opt_image_map.keys():
                f.write("Page " + str(opt_count) + " " + str(opt_image_map[opt_count]))
            else:
                f.write("Page " + str(opt_count) + " temp")
            f.write("\n")
            urls = opt_urls_map[opt_count]
            ui_text = read_page_text(opt_count)
            privacy_tuples = []
            for url in urls:
                if url not in url_privacy_tuples_map.keys():
                    continue
                for tup in url_privacy_tuples_map[url]:
                    if tup not in privacy_tuples and tup[1] != '':
                        privacy_tuples.append(tup)
            for idx in range(len(privacy_tuples)):
                if idx == len(privacy_tuples) - 1:
                    f.write(str(privacy_tuples[idx][0]) + " " + str(privacy_tuples[idx][1]))
                else:
                    f.write(str(privacy_tuples[idx][0]) + " " + str(privacy_tuples[idx][1]) + ",")
            f.write("\n")
            for idx in range(len(ui_text)):
                if idx == len(ui_text) - 1:
                    f.write(str(ui_text[idx]))
                else:
                    f.write(str(ui_text[idx]) + ",")
            f.write("\n")
        f.flush()
        f.close()

