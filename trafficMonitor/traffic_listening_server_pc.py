import os
import json
import urllib.parse as up

import urllib
import config
import sys
sys.path.append(r'G:\\miniapp\\XPOScope-main') # 添加上级目录到模块搜索路径
MITM_DIR = config.MINI_APP_LOG+ "mitmproxy"   # 统一的根目录
HEADER_KEYS = (
    "authorization", "cookie", "x-token", "x-auth-token",
    "x-csrf-token", "referer", "user-agent"
)

from replay.core.ControllerRequestRecord import ControllerRequestRecord
import replay.core.Analyzer as Analyzer
import replay.lib.Utils as Utility
import time

def save_to_analysis_db(flow_data):
    """
    将 mitmproxy 的数据流转换为 Analysis 框架需要的格式并存储
    """
    ctrl = ControllerRequestRecord()
    
    # 1. 基础字段提取
    meta = flow_data.get("__meta", {})
    url = meta.get("url") or flow_data.get("url", "")
    method = meta.get("method", "GET").lower()
    
    # 提取参数 (需要区分 GET/POST)
    get_params_dict = {}
    post_params_dict = {}
    
    # 简单处理：如果是 GET，参数在 query；如果是 POST，参数在 payload
    # 注意：这里需要你根据 flow_data 的实际结构细化
    if method == 'get':
        get_params_dict = flow_data # 假设 flow_data 里混杂了 query
    else:
        post_params_dict = flow_data
        
    # 将字典转为字符串存库
    get_params_str = Utility.dict2json(get_params_dict)
    post_params_str = Utility.dict2json(post_params_dict)

    # 2. 调用 Analyzer 进行敏感信息分析 (关键！)
    # 分析 URL Path
    path_list, path_sensitive = Analyzer.path_analysis(url)
    # 分析 GET 参数
    origin_get, sensitive_get = Analyzer.params_analysis(get_params_str, _is_pay_load=False)
    # 分析 POST 参数
    origin_post, sensitive_post = Analyzer.params_analysis(post_params_str, _is_pay_load=True)
    
    # 假设 flow_data 里还没有 response body (因为这是 req 阶段)
    # 如果你在 link 函数里已经把 req/resp 合并了，这里就能拿到 response
    # 假设暂时为空，或者只处理 Response 阶段的数据
    response_str = "" 
    response_sensitive = ""
    
    # 3. 构造数据包
    record_data = {
        'flow_id': meta.get("req_id", Utility.md5(str(time.time()))),
        'host': urllib.parse.urlparse(url).hostname,
        'port': 80, # 默认
        'method': method,
        'url': url,
        'referer': flow_data.get('referer', ''),
        'content_type': 'json', # 假设
        'response': response_str,
        'response_exists_sensitive': 0,
        'response_sensitive': "",
        
        # Path 分析结果
        'path': json.dumps(path_list),
        'path_exist_sensitive': len(path_sensitive),
        'path_sensitive': json.dumps(path_sensitive),
        
        # GET 分析结果
        'get_params': get_params_str,
        'get_exist_sensitive': len(sensitive_get),
        'get_sensitive': json.dumps(sensitive_get),
        
        # POST 分析结果
        'post_params': post_params_str,
        'post_exist_sensitive': len(sensitive_post),
        'post_sensitive': json.dumps(sensitive_post),
    }
    
    # 4. 存入数据库
    ctrl.add_record(record_data)

def _append_replay_log(url: str, privacy_data: dict):
    """
    把一条 request 记录写到 ./mitmproxy/{host}/requests.jsonl
    并为每个 host 生成 header.json（若还不存在）。
    只处理 dir == 'req' 的数据。
    """
    try:
        meta = privacy_data.get("__meta", {}) or {}
        if meta.get("dir") != "req":
            return

        method = meta.get("method", "GET").upper()
        full_url = meta.get("url") or url
        host = up.urlparse(full_url).hostname or "unknown_host"

        # 1) 组装 params / headers
        params = {}
        headers = {}
        for k, v in privacy_data.items():
            if k == "__meta":
                continue
            lk = k.lower()
            if lk in HEADER_KEYS:
                headers[lk] = v
            else:
                params[k] = v

        # 2) 写 request.jsonl
        host_dir = os.path.join(MITM_DIR, host)
        os.makedirs(host_dir, exist_ok=True)
        log_path = os.path.join(host_dir, "requests.jsonl")
        rec = {
            "host": host,
            "url": full_url,
            "method": method,
            "params": params,
            "headers": headers,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 3) 如果还没有 header.json，就生成一份
        header_path = os.path.join(host_dir, "header.json")
        if (headers) and (not os.path.exists(header_path)):
            with open(header_path, "w", encoding="utf-8") as f:
                json.dump({"request_header": headers}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 不要影响主逻辑
        print(f"[replay-log] write failed: {e}")
