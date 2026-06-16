# strategy/replay_main_pc.py
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
# from RequestConstructor import build_url, get_header
from replay.core.RequestConstructor import build_url, get_header
def _iter_host_logs(root_dir=config.MITM_DIR):
    """遍历 ./mitmproxy 下所有 hosst 的 requests.jsonl"""
    if not os.path.isdir(root_dir):
        return
    for host in os.listdir(root_dir):
        host_dir = os.path.join(root_dir, host)
        log_path = os.path.join(host_dir, "requests.jsonl")
        if os.path.isfile(log_path):
            yield host, log_path


def replay_one_log(host: str,
                   log_path: str,
                   start_index: int = 1,
                   end_index: int = 5,
                   out_dir: str = config.MINI_APP_LOG + "replay_result"):
    """
    对单个 host 的 requests.jsonl 做重放。
    - 使用 RequestConstructor.build_url 对 params 做序列化变形；
    - 用 requests 发包；
    - 把结果写到 ./replay_result/{host}.replay.jsonl
    """
    os.makedirs(out_dir, exist_ok=True)
    result_path = os.path.join(out_dir, f"{host}.replay.jsonl")

    # header.json 兼容你原来的 get_header()
    headers = get_header(host) or {}

    with open(log_path, "r", encoding="utf-8") as fin, \
         open(result_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            url = rec.get("url")
            method = (rec.get("method") or "GET").upper()
            params = rec.get("params") or {}

            # 使用你的 build_url 生成参数序列
            try:
                url_list = build_url(url, json.dumps(params, ensure_ascii=False),
                                     start_index=start_index,
                                     end_index=end_index)
            except Exception as e:
                print(f"[replay] build_url failed for {url}: {e}")
                continue

            for replay_url in url_list:
                record = {
                    "host": host,
                    "orig_url": url,
                    "replay_url": replay_url,
                    "method": method,
                }
                try:
                    if method == "GET":
                        resp = requests.get(replay_url, headers=headers, timeout=5)
                    else:
                        # 先简单版本：非 GET 只重放 URL，不带 body
                        resp = requests.request(method, replay_url,
                                                headers=headers, timeout=5)
                    record["status"] = resp.status_code
                    record["resp_snippet"] = resp.text[:200]
                except Exception as e:
                    record["error"] = repr(e)

                fout.write(json.dumps(record, ensure_ascii=False) + "\n")


def replay_all_hosts(root_dir: str = config.MITM_DIR,
                     start_index: int = 1,
                     end_index: int = 5,
                     out_dir: str = config.MINI_APP_LOG + "replay_result"):
    """
    对所有 host 做一次重放。给 xpochecker_pc 调用。
    """
    print("[REPLAY] start replaying captured traffic...")
    for host, log_path in _iter_host_logs(root_dir):
        print(f"[REPLAY] host={host}, log={log_path}")
        replay_one_log(host, log_path,
                       start_index=start_index,
                       end_index=end_index,
                       out_dir=out_dir)
    print("[REPLAY] all hosts finished.")
