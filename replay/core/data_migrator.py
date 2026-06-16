import os
import sqlite3
import json
import time
import urllib.parse
# 导入第①套代码的核心模块
from replay.core.ControllerRequestRecord import ControllerRequestRecord
import replay.core.Analyzer as Analyzer
import replay.lib.Utils as Utility
import config
# import replay.core.db_operate as db_operate

from replay.lib.DB import DB
from trafficMonitor import traffic_utils  # 导入 DB 类
DB_PATH = os.path.join(config.MINI_APP_LOG, "scan_data_origin.db")
def get_target_hosts(target_hosts=None):
    if target_hosts is None:
        target_hosts = set()
    IGNORE_HOSTS = [
        "servicewechat.com", 
        "mp.weixin.qq.com", 
        "aegis.qq.com", 
        "mmbiz.qpic.cn", 
        "wxsnsdy.wxs.qq.com",
        "wx.qlogo.cn",
        "googleapis.com",
        "qq.com.cn",
    ]
    try:
        # 1. 连接数据库
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 2. 直接查询去重后的 Host
        c.execute("SELECT DISTINCT host FROM traffic WHERE host IS NOT NULL AND host != ''")
        rows = c.fetchall()
        conn.close()

        # 3. 过滤并添加到集合
        for row in rows:
            h = row[0]
            # 过滤掉黑名单中的域名
            if any(ignored in h for ignored in IGNORE_HOSTS):
                continue
            target_hosts.add(h)
            
    except Exception as e:
        print(f"[Step 2 Error] 从数据库提取 Host 失败: {e}")

    if not target_hosts:
        print("未发现有效业务 Host，跳过重放。")
        return None
    else:
        print(f"待重放的目标 Host: {target_hosts}")
        return target_hosts

def clear_analysis_db():
    db = DB()
    db.clear_tables()

def migrate_simple_to_analysis(mini_app_name=None):
    print("[Migrate] 开始将原始流量导入分析数据库...")
    
    conn = sqlite3.connect(DB_PATH)
    # conn.row_factory = sqlite3.Row # 这行如果报错就注释掉，我们用下面的方法手动映射
    c = conn.cursor()
    
    # 1. 查询数据
    sql = "SELECT * FROM traffic WHERE resp_body != '' AND resp_body IS NOT NULL"
    if mini_app_name:
        sql += f" AND mini_app_name = '{mini_app_name}'"
        
    c.execute(sql)
    rows = c.fetchall()
    
    # ★★★ 关键修复：动态获取列名索引，防止错位 ★★★
    # 获取所有列名 ['req_id', 'host', 'url', ...]
    col_names = [description[0] for description in c.description]
    try:
        idx_req_id = col_names.index('req_id')
        idx_url = col_names.index('url')
        idx_method = col_names.index('method')
        idx_resp_body = col_names.index('resp_body')
        idx_req_params = col_names.index('req_params')
    except ValueError as e:
        print(f"[Migrate Fatal Error] 数据库表结构缺失关键列: {e}")
        print(f"当前列名: {col_names}")
        conn.close()
        return

    conn.close()
    
    print(f"--- 待迁移记录数: {len(rows)} ---")
    
    ctrl = ControllerRequestRecord()
    count = 0
    db_instance = DB()
    for row in rows:
        try:
            # 使用动态索引取值
            req_id = row[idx_req_id]
            url = row[idx_url]
            method = row[idx_method]
            method = method.lower() if method else "get"
            
            # ★★★ 强制转为字符串，防止如果是 int 导致后续报错 ★★★
            resp_body = str(row[idx_resp_body]) if row[idx_resp_body] is not None else ""
            raw_params = row[idx_req_params] or "{}"
            # print(resp_body)

            # --- 1. 参数解析 ---
            try:
                flow_data = json.loads(raw_params)
            except:
                flow_data = {}

            get_params_dict = {}
            post_params_dict = {}
            
            parsed = urllib.parse.urlparse(url)
            if parsed.query:
                get_params_dict = dict(urllib.parse.parse_qsl(parsed.query))
            
            if flow_data:
                clean_data = {k:v for k,v in flow_data.items() if k != "__meta"}
                if method == 'post':
                    post_params_dict = clean_data
                elif method == 'get' and not get_params_dict:
                    get_params_dict = clean_data

            # --- 2. 敏感分析 ---
            try:
                sensitive_get = traffic_utils.detect_privacy(get_params_dict)
                sensitive_post = traffic_utils.detect_privacy(post_params_dict)
                
                sensitive_resp = []
                if resp_body:
                    # print(resp_body)
                    body_to_scan = resp_body
                    # 尝试处理 raw_response 包裹
                    if "raw_response" in resp_body:
                        try:
                            tmp = json.loads(resp_body)
                            if "raw_response" in tmp:
                                body_to_scan = tmp["raw_response"]
                        except:
                            pass
                    
                    if body_to_scan.strip().startswith(("{", "[")):
                        try:
                            sensitive_resp = traffic_utils.detect_privacy(json.loads(body_to_scan))
                        except:
                            # pass
                            print(f"[Migrate] 响应体 JSON 解析失败，尝试文本分析...")
                            sensitive_resp = traffic_utils.detect_privacy(body_to_scan)
            except Exception as e:
                print(f"[Analysis Error] {url}: {e}")
                sensitive_get, sensitive_post, sensitive_resp = [], [], []
            # print("sensitive_get")
            # print(sensitive_get)
            # print("sensitive_post")
            # print(sensitive_post)
            # print("sensitive_resp")
            # print(sensitive_resp)
                
            # ★★★ 新增：种子收集逻辑 (Harvesting) ★★★
            # 1. 从 GET 参数中收集
            if sensitive_get:
                for key, seed_type in sensitive_get:
                    val = get_params_dict.get(key)
                    if val: db_instance.save_seed(seed_type, val, url,mini_app_name)

            # 2. 从 POST 参数中收集
            if sensitive_post:
                for key, seed_type in sensitive_post:
                    val = post_params_dict.get(key)
                    if val: db_instance.save_seed(seed_type, val, url,mini_app_name)

            # 3. 从 响应体 (Response) 中收集 (这是最重要的来源！拿到别人的ID)
            if sensitive_resp:
                # sensitive_resp 的结构是 [(key, value), (key, value)...]
                # 例如: [('user_id', '1453...'), ('phone_number', '159****3322')]
                
                for key, value in sensitive_resp:
                    try:
                        # A. 获取种子类型 (Category)
                        # 我们只有字段名(key)，需要问 traffic_utils 它是属于哪类隐私 (如 phone, userid)
                        # judge_key 返回 (key, category)
                        _, seed_type = traffic_utils.judge_key(key)

                        # 如果没有识别出类型，或者值为空，跳过
                        if not seed_type or not value:
                            continue

                        val_str = str(value)

                        # B. 关键过滤：不要存“脱敏”数据！
                        # 你的日志显示 phone_number 是 "159****3322"，这种带星号的数据拿去重放是没用的
                        # 我们只存完整的、有攻击价值的数据
                        if "*" in val_str:
                            # print(f"  [Seed Ignored] 忽略脱敏数据: {key}={val_str}")
                            continue
                        
                        # 过滤太短的垃圾数据
                        if len(val_str) < 1:
                            continue

                        # C. 存入种子表
                        # print(f"  [Seed Found] {seed_type}: {val_str}")
                        db_instance.save_seed(seed_type, val_str, url, mini_app_name)
                        
                    except Exception as e:
                        print(f"[Seed Error] 处理 {key} 失败: {e}")

            def format_sensitive(res_list):
                if not res_list: return ""
                try:
                    return json.dumps(dict(res_list), ensure_ascii=False)
                except:
                    return str(res_list)
            
            
            # print(resp_body)
            # --- 3. 构造数据 ---
            record_data = {
                'flow_id': req_id,
                'host': urllib.parse.urlparse(url).hostname or "unknown",
                'port': 80, 
                'method': method,
                'url': url,
                'referer': "", 
                'content_type': 'json', 
                'response': resp_body,
                'response_exists_sensitive': len(sensitive_resp),
                'response_sensitive': format_sensitive(sensitive_resp),
                'path': "", 'path_exist_sensitive': 0, 'path_sensitive': "",
                'get_params': json.dumps(get_params_dict, ensure_ascii=False),
                'get_exist_sensitive': len(sensitive_get),
                'get_sensitive': format_sensitive(sensitive_get),
                'post_params': json.dumps(post_params_dict, ensure_ascii=False),
                'post_exist_sensitive': len(sensitive_post),
                'post_sensitive': format_sensitive(sensitive_post),
            }
            
            ctrl.add_record(record_data)
            count += 1
            
        except Exception as e:
            print(f"[Migrate Error] Row ID {row[idx_req_id]}: {e}")
            # import traceback
            # traceback.print_exc()
            
    print(f"[Migrate] 成功迁移 {count} 条记录到 Analysis 数据库。")


