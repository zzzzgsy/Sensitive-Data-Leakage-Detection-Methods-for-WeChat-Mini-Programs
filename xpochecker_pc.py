import json
import multiprocessing
import os
import sys
import time
import re
import socket
import threading

import urllib
import eventlet
import config
from replay.lib.DB import DB
from trafficMonitor import traffic_utils as traffic_utils
import xlrd
import MiniAppLog.report as report
import replay.core.db_operate as db_operate
from trafficMonitor.traffic_listening_server_pc import _append_replay_log, save_to_analysis_db
import replay.Replay as replay_analysis_pc
import replay.core.data_migrator as data_migrator  # 导入刚才写的文件
def get_last_opt():
    opt_path = config.PAGE_TEXT_PATH + "opt.txt"
    if not os.path.exists(opt_path):
        return -1
    with open(opt_path) as f:
        last_opt = f.read()
        f.close()
    if last_opt == '':
        return -1

    return last_opt


def read_page_text(page_index):
    page_file_path = config.PAGE_TEXT_PATH + str(page_index) + ".txt"
    # ★★★ 新增：文件不存在时的兜底判断 ★★★
    if not os.path.exists(page_file_path):
        # 针对 999999 (启动动作) 或其他丢失文件的情况，返回空列表，防止报错中断
        # print(f"[Report] Warning: Text file not found: {page_file_path}")
        return []
    res = []
    try:
        with open(page_file_path, 'r', encoding='utf-8') as f:
            dump_strs = f.readlines()
        # f.close() # with 语句会自动 close，但这行留着也没事
        for dump_str in dump_strs:
            new_str = re.sub('\n', "", dump_str)
            res.append(new_str)
    except Exception as e:
        print(f"[Report] Read text error {page_index}: {e}")
        return []
        
    return res

def traffic_listening_server(url_traffic_map, url_page_index_map, url_ts_map, events_map, mini_app_name):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', config.TCP_PORT))
    s.listen()
    start_time = time.time()
    while True:
        sock, addr = s.accept()
        thread_server = threading.Thread(target=link,args=(sock, addr, url_traffic_map, url_page_index_map, url_ts_map, events_map, mini_app_name))
        thread_server.start()
        if time.time() - start_time > config.MINI_APP_TEST_TIME + 10:
            break
    s.close()

def link(sock, addr, url_traffic_map, url_page_index_map, url_ts_map, events_map,mini_app_name):
    print("Accept new connection from %s:%s..." % addr)
    sock.send('Connect success!'.encode())
    db_instance = DB()
    f = sock.makefile('rb', buffering=65536)
    while True:
        try:
            # 每次读取一行（直到遇到 \n）
            line = f.readline()
            # print("[DB] Saving traffic\n...")
            # 如果读到空字节，说明连接断开
            if not line: 
                break
                
            # 去掉空白符
            line = line.strip()
            if not line:
                continue

            # 解析 JSON
            try:
                recv_json = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[Socket Error] JSON解析失败，跳过此包: {e}")
                # print(f"错误数据片段: {line[:50]}...")
                continue

            # --- 下面是你原有的业务逻辑 (保持不变) ---
            opt_type = recv_json.get('opt_type')
            
            if opt_type == 1:
                data = recv_json.get('data') or {}
                url  = recv_json.get('url')  or ""
                
                if not isinstance(data, dict): continue

                meta   = data.get("__meta", {}) if isinstance(data, dict) else {}
                req_id = str(meta.get("req_id") or "")
                ts     = float(meta.get("ts", time.time()))
                dire   = (meta.get("dir") or "").lower()
                url0   = meta.get("url") or url
                
                # print(f"[FLOW] {req_id} {dire} {url0}") # 调试用

                # 存库
                try:
                    db_instance.save_traffic(mini_app_name, data)
                except Exception as e:
                    print(f"[DB] Save Error: {e}")
                
                # 写重放日志
                _append_replay_log(url0, data)
                # save_to_analysis_db(data)

                # 聚合 events_map (逻辑保持不变)
                if req_id:
                    ev = events_map.get(req_id, {})
                    if "url" not in ev and url0: ev["url"] = url0
                    if "opt" not in ev:
                        last_opt = get_last_opt()
                        if last_opt != -1: ev["opt"] = int(last_opt)
                    
                    if dire == "req":
                        ev["req"] = data
                        ev["ts_req"] = ts
                    elif dire == "resp":
                        ev["resp"] = data
                        ev["ts_resp"] = ts
                    
                    events_map[req_id] = ev
                    
                    # Map 更新 (逻辑保持不变)
                    suffix = "REQ" if dire == "req" else ("RESP" if dire == "resp" else "EVT")
                    compat_key = f"{url0}#{suffix}#{req_id}"
                    url_ts_map[compat_key] = ts
                    
                    if compat_key not in url_traffic_map:
                        last_opt_count = get_last_opt()
                        if last_opt_count != -1:
                            url_page_index_map[compat_key] = last_opt_count
                    url_traffic_map[compat_key] = data
                else:
                    # 兜底逻辑
                    if url not in url_traffic_map.keys():
                        last_opt_count = get_last_opt()
                        if last_opt_count != -1:
                            url_traffic_map[url] = data
                            url_page_index_map[url] = last_opt_count
                            url_ts_map[url] = ts
                    else:
                        url_ts_map[url] = ts

            elif opt_type == 2:
                break
                
        except Exception as e:
            print(f"[Link Loop Error] {e}")
            break

    # 关闭文件流和Socket
    try:
        f.close()
        sock.close()
    except:
        pass

def run_traffic_monitor():
    os.system("python ./trafficMonitor/traffic_monitor_pc.py")


def run_dynamic_exerciser(mini_app_plat, mobile_model, mini_app_name, queue: multiprocessing.Queue):
    # os.system("python ./dynamicExerciser/dynamic_exerciser.py {0} {1} {2}".format(mini_app_plat, mobile_model, mini_app_name))
    print("开始运行Dynamic Exerciser")
    os.system(f"python ./dynamicExerciser/dynamic_exerciser_pc.py 1 0  {mini_app_name}")
    queue.put("end")

import subprocess
import sys

def run_dynamic_exerciser(mini_app_plat, mobile_model, mini_app_name, queue: multiprocessing.Queue):
    print("开始运行Dynamic Exerciser")
    print(sys.executable)
    # 不要写死 1 0，用传进来的参数
    cmd = [
        sys.executable,                     # 当前虚拟环境里的 python
        "./dynamicExerciser/dynamic_exerciser_pc.py",
        str(mini_app_plat),
        str(mobile_model),
        mini_app_name,
    ]

    proc = subprocess.Popen(cmd)
    try:
        # 等待 N 秒（建议直接用你原来的 MINI_APP_TEST_TIME）
        proc.wait(timeout=config.MINI_APP_TEST_TIME)
        queue.put({"status": "end", "returncode": proc.returncode})
    except subprocess.TimeoutExpired:
        print(f"dynamic_exerciser 超过 {config.MINI_APP_TEST_TIME} 秒未结束，准备杀掉子进程")
        proc.kill()
        proc.wait(timeout=10)
        queue.put({"status": "timeout"})

def run_traffic_listening_server(url_traffic_map, url_page_index_map, url_ts_map, events_map, mini_app_name):
    # eventlet.monkey_patch()
    with eventlet.Timeout(config.MINI_APP_TEST_TIME + 20, False):
        traffic_listening_server(url_traffic_map, url_page_index_map, url_ts_map, events_map, mini_app_name)
    print("listening server end!")
def get_target_mini_app_names(type_name):
    excel = xlrd.open_workbook(config.WORK_BOOK)
    sheet = excel.sheet_by_index(0)
    cols_num = sheet.ncols
    target_col_vals = None
    for i in range(cols_num):
        col_vals = sheet.col_values(i)
        if col_vals[0] == type_name:
            target_col_vals = col_vals
            break
    return target_col_vals

if __name__ == "__main__":
    # os.system("adb reverse tcp:9999 tcp:9999")
    args = sys.argv
    mini_app_platform = 1
    mobile_model = 1
    # mini_app_name = "SUPERHERO健身" 
    mini_app_name = args[3].strip("'")
    
    print("开始生成{0}Log:".format(mini_app_name))
    # db_utils.init_db()
    db = DB()
    data_migrator.clear_analysis_db()
    queue = multiprocessing.Queue(maxsize=1)
    processes = []
    manager = multiprocessing.Manager()
    url_traffic_map = manager.dict()
    url_page_index_map = manager.dict()
    url_ts_map = manager.dict()  # 新增
    events_map = manager.dict()   # ★ 新增：req_id -> 聚合对象
    # traffic_listen_process = multiprocessing.Process(target=run_traffic_listening_server,
    #                                                  args=(url_traffic_map, url_page_index_map, url_ts_map))
    traffic_listen_process = multiprocessing.Process(target=run_traffic_listening_server,
                                                     args=(url_traffic_map, url_page_index_map, url_ts_map, events_map, mini_app_name))   # ★ 传过去
    processes.append(traffic_listen_process)
    traffic_listen_process.start()
    time.sleep(1)
    # print("ok1")
    mitmproxy_process = multiprocessing.Process(target=run_traffic_monitor)
    processes.append(mitmproxy_process)
    mitmproxy_process.start()
    # time.sleep(3)
    dynamic_exerciser_process = multiprocessing.Process(target=run_dynamic_exerciser, args=(
        mini_app_platform, mobile_model, mini_app_name, queue,))
    processes.append(dynamic_exerciser_process)
    dynamic_exerciser_process.start()
    # print("ok2")

    ret = queue.get()

    # 3. 先等 dynamic_exerciser 自己退出（更干净）
    dynamic_exerciser_process.join(timeout=5)
    # 4. 再主动“停机”另外两个：mitmproxy + traffic_listening_server
    for proc in (mitmproxy_process, traffic_listen_process):
        if proc.is_alive():
            proc.terminate()   # 这里就是你说的“停机信号”
            proc.join(timeout=5)

    # ★ 新增：抓包结束后做重放
    # from replay.core.main_replay import replay_all_hosts

    # # ★ 在抓包结束后、报告生成前做一次重放
    # try:
    #     replay_all_hosts(root_dir=config.MINI_APP_LOG+ "mitmproxy",
    #                     start_index=1,
    #                     end_index=5,
    #                     out_dir= config.MINI_APP_LOG + "replay_result")
    # except Exception as e:
    #     print(f"[REPLAY] replay_all_hosts failed: {e}")


    
    print("Step 1: 正在将抓包数据迁移至分析数据库...")
    # ★★★ 新增：先清空旧数据 ★★★
    
    # 把数据从 traffic 表清洗进 request_record 表
    data_migrator.migrate_simple_to_analysis(mini_app_name)

    print("Step 2: 开始基于数据库进行智能重放 (第①套逻辑)...")
    # 提取目标 Host (从 url_traffic_map 或 数据库中提取)
    target_hosts = data_migrator.get_target_hosts()
    for host in target_hosts:
        print(f"Replaying Host: {host}")
        try:
            # 调用 replay.py 的 run 方法
            replay_analysis_pc.run(host)
        except Exception as e:
            print(f"Replay Error for {host}: {e}")
            import traceback
            traceback.print_exc()

    # print("Step 2: 开始基于数据库进行智能重放 (第①套逻辑)...")
    # # 提取目标 Host (从 url_traffic_map 或 数据库中提取)
    # target_hosts = set()
    # for url in url_traffic_map.keys():
    #     try:
    #         h = urllib.parse.urlparse(url).hostname
    #         # if h and "servicewechat" not in h: # 排除微信基础域名
    #         if h:
    #             target_hosts.add(h)
    #     except:
    #         pass
    # if not target_hosts:
    #     print("未发现有效业务 Host，跳过重放。")
    # for host in target_hosts:
    #     print(f"Replaying Host: {host}")
    #     try:
    #         # 调用 replay.py 的 run 方法
    #         replay_analysis_pc.run(host)
    #     except Exception as e:
    #         print(f"Replay Error for {host}: {e}")
    #         import traceback
    #         traceback.print_exc()

    print("ok2")
    import psutil
    from signal import SIGTERM

    for proc in psutil.process_iter(['pid','name']):
        try:
            for nc in proc.net_connections(kind='inet'):
                if nc.laddr and nc.laddr.port == 8080 :
                    print("KILL Mitmproxy")
                    proc.send_signal(SIGTERM)   # 或者 proc.terminate()
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    try:
        report.generate_report(mini_app_name,mini_app_platform, url_traffic_map, url_page_index_map)
        report.generate_evidence_reports(mini_app_name, mini_app_platform, url_traffic_map, url_page_index_map, url_ts_map)
    except Exception as e:
        print(e)

# 处理运行过程产生的图片和数据，主要是截图的转移以及文本文件的删除
