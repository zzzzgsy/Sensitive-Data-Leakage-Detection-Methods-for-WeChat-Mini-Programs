import json

import os
import urllib.request
# 1) 清理环境变量里的代理
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
          "http_proxy","https_proxy","all_proxy","no_proxy","proxy","PROXY"):
    os.environ.pop(k, None)

# 2) 告诉 urllib / requests 不要用系统代理
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

try:
    import requests
    requests.sessions.Session.trust_env = False
except Exception:
    pass

urllib.request.getproxies = (lambda: {})

import requests
import urllib
import config
import json
import argparse

import requests
import replay.core.RequestConstructor as ReqConstr
from replay.core.ControllerRequestRecord import ControllerRequestRecord
import replay.lib.Utils as Utility
import replay.core.Analyzer as Analyzer



def init(_host, _method='get', _content_type='json'):
    where_condition = ("host='{host}' and content_type='{content_type}' and method='{method}' and {method}_params!='' "
                    #    "and response_exists_sensitive>=0 "
                       "and ("
                    "  response_exists_sensitive > 0 "
                    "  or get_exist_sensitive > 0 "
                    "  or post_exist_sensitive > 0 "
                    ")"
                       ).format(host=_host, content_type=_content_type, method=_method)
    fields = "distinct(url) as url,referer,{method}_params,{method}_sensitive,response".format(method=_method)
    CtrlReqRecd = ControllerRequestRecord()
    rs = CtrlReqRecd.query_record(where=where_condition, fields=fields)
    header = ReqConstr.get_header(_host)
    rs_gen = []
    if _method == 'get':
        for rs_item in rs:
            # print(rs_item)
            rs_gen.append({"origin": rs_item, "gen": ReqConstr.build_url(rs_item["url"], rs_item[_method + "_params"])})
    elif _method == 'post':
        for rs_item in rs:
            # if  "https://hlwyy.puaihospital.cn/orgine-poweruap-api-proxy/gateway" in rs_item["url"]:
            #     print(rs_item["url"], rs_item[_method + "_params"])
            rs_gen.append({"origin": rs_item, "url": rs_item["url"], "gen": ReqConstr.build_params(rs_item[_method + "_params"])})
    return {"header": header, "rs": rs_gen}


def add_record(_data):
    origin_params, sensitive_params = Analyzer.content_analysis(Utility.remove_html_tags(_data["response"]))
    sensitive_params_len = 0
    sensitive_info = ''
    if sensitive_params is not None and len(sensitive_params) > 0:
        sensitive_params_len = len(sensitive_params)
        sensitive_info = json.dumps(sensitive_params, ensure_ascii=False)
    second_record_item = {
        "host": _data['host'], "method": _data['method'], "referer": _data['rs_item']['origin']['referer'],
        "content_type": "json", "origin_url": _data['rs_item']['origin']['url'],
        "url": _data['gen_url'], "response": _data["response"], "response_exists_sensitive": sensitive_params_len,
        "response_sensitive": sensitive_info, "gen_params": _data['gen_params']
    }
    CtrlReqRecd = ControllerRequestRecord()
    CtrlReqRecd.add_request_record_second(second_record_item)

# ★★★ 新增：差异对比辅助函数 ★★★
# def get_diff_str(original_dict, new_dict):
#     diffs = []
#     for k, v_new in new_dict.items():
#         v_old = original_dict.get(k)
#         # 如果值不同，记录下来
#         if str(v_new) != str(v_old):
#             diffs.append(f"{k}: {v_old} -> {v_new}")
    
#     if not diffs:
#         return "No Changes (Original Replay)"
#     return " | ".join(diffs)
def get_diff_str(original_dict, new_dict):
    diffs = []
    
    # 1. 如果不是字典，直接对比字符串值
    if not isinstance(new_dict, dict) or not isinstance(original_dict, dict):
        if str(original_dict) != str(new_dict):
            return f"Full Change: {str(original_dict)[:20]}... -> {str(new_dict)[:20]}..."
        return "No Changes"

    # 2. 正常的字典对比逻辑
    for k, v_new in new_dict.items():
        v_old = original_dict.get(k)
        if str(v_new) != str(v_old):
            diffs.append(f"{k}: {v_old} -> {v_new}")
    
    if not diffs:
        return "No Changes (Original Replay)"
    return " | ".join(diffs)

def get_deep_diff(original, new_val, path=""):
    """递归对比两个对象，找出深层差异"""
    diffs = []
    
    # 1. 尝试解析 JSON 字符串进行对比
    if isinstance(original, str) and isinstance(new_val, str):
        if original.startswith("{") and new_val.startswith("{"):
            try:
                o_json = json.loads(original)
                n_json = json.loads(new_val)
                return get_deep_diff(o_json, n_json, path)
            except:
                pass

    # 2. 字典对比
    if isinstance(original, dict) and isinstance(new_val, dict):
        all_keys = set(original.keys()) | set(new_val.keys())
        for k in all_keys:
            # 递归
            new_path = f"{path}.{k}" if path else k
            d = get_deep_diff(original.get(k), new_val.get(k), new_path)
            if d: diffs.extend(d)
        return diffs
        
    # 3. 基础值对比
    if str(original) != str(new_val):
        # 优化显示：如果太长（比如整个HTML），只显示前50字符
        o_str = str(original)
        n_str = str(new_val)
        if len(o_str) > 50: o_str = o_str[:20] + "..."
        if len(n_str) > 50: n_str = n_str[:20] + "..."
        
        return [f"{path}: {o_str} -> {n_str}"]
        
    return []

def replay(_host, _method='get'):
    rs = init(_host, _method)
    # print("==========second_request - rs==========")
    # print(rs)
    # print("==========second_request - rs==========")
    # header = json.loads(rs["header"])
    # header = rs["header"]
    
    header = rs.get("header") # 使用 .get 更安全
    
    if header is None:
        print(f"[Warning] No header found for {_host}, skipping header processing.")
        header = {} # 给一个空字典，防止下面报错


    keys_to_remove = [k for k in header.keys() if k.lower() == 'content-length']
    for k in keys_to_remove:
        header.pop(k)

    print(f"--- Start Replay for {_host} ---")

    # resp = []
    for rs_item in rs["rs"]:
        # tmp_resp = []
        try:
            origin_params_str = rs_item["origin"].get(f"{_method}_params", "{}")
            origin_params = json.loads(origin_params_str)
        except:
            origin_params = {}

        for gen in rs_item["gen"]:
            compare_target = gen
            if isinstance(gen, str) and _method == 'get':
                try:
                    from urllib.parse import urlparse, parse_qsl
                    # 提取 URL 中的 query 部分 (?a=1&b=2)
                    parsed = urlparse(gen)
                    # 转为字典 {'a': '1', 'b': '2'}
                    query_dict = dict(parse_qsl(parsed.query))
                    if query_dict:
                        compare_target = query_dict
                except:
                    pass # 解析失败就还用原始字符串比，反正 get_diff_str 现在支持字符串了
            
            # 2. 调用对比函数 (传入处理过的 compare_target)
            diff_msg = get_diff_str(origin_params, compare_target)
            diff_list = get_deep_diff(origin_params, compare_target)
            # ==================== ★★★ 修复结束 ★★★ ====================

            if not diff_list and diff_msg == "No Changes (Original Replay)":
                 # print("  [Skip] No changes")
                 continue

            clean_gen = gen.copy() if isinstance(gen, dict) else gen
            if isinstance(clean_gen, dict):
                # 定义要剔除的杂质
                dirty_keys = ['referer', 'user-agent', 'host', 'content-type', 'content-length']
                for k in dirty_keys:
                    # 不区分大小写的删除
                    matched_keys = [dk for dk in clean_gen.keys() if dk.lower() == k]
                    for mk in matched_keys:
                        clean_gen.pop(mk)
            
            _data = {
                "host": _host, "method": _method, "rs_item": rs_item
            }
            if _method == 'get':
                t_resp = requests.get(clean_gen, headers=header)
                res_txt = t_resp.text.replace("'", "")
                res_txt = Utility.remove_html_tags(res_txt)
                _data['response'] = res_txt
                _data['gen_url'] = clean_gen
                _data['gen_params'] = clean_gen.split('?')[1]
            elif _method == 'post':
                # if  "https://hlwyy.puaihospital.cn/orgine-poweruap-api-proxy/gateway" in rs_item["url"] and "1452609057689214976" in str(clean_gen):
                #     print("POST URL:", rs_item['url'])
                #     print("POST Data:", clean_gen)
                #     print("headers:",header)
                # header2 = dict(header)
                # header2["Content-Type"] = "application/json;charset=UTF-8"
                # header2["Accept"] = "application/json, text/javascript, */*; q=0.01"
                # header2["X-Requested-With"] = "XMLHttpRequest"
                t_resp = requests.post(rs_item['url'], headers=header, json=clean_gen)
                print(t_resp)
                res_txt = t_resp.text.replace("'", "")
                res_txt = Utility.remove_html_tags(res_txt)
                _data['response'] = res_txt
                _data['gen_url'] = rs_item['url']
                _data['gen_params'] = json.dumps(clean_gen)
            add_record(_data)

            # ★★★ 2. 打印日志 ★★★
            diff_msg = " | ".join(diff_list)
            print(f"[{_method.upper()}] {diff_msg}")
            # if "user_id" in diff_msg or "userid" in diff_msg:
            #     print("  >> Potential Sensitive Change Detected!")
            #     print("URL:", _data['gen_url'])
            #     print("Params:", _data['gen_params'])
            # print("URL:", _data['gen_url'])
            # print("【{}】Current URL & Paras：{},{}".format(_method, _data['gen_url'], _data['gen_params']))
    print("【{}】Replay Completed".format(_method))


def replay_post(_host):
    replay(_host, 'post')


def replay_get(_host):
    replay(_host, 'get')


def run(_host):
    if not _host: return
    replay_get(_host)
    replay_post(_host)


# ★★★ 关键修改：缩进并放入 main 判断中
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='')
    args = parser.parse_args()
    host = args.host
    print("host:", host)
    run(host)