import json
import socket
import time

import config
# trafficMonitor/traffic_transfer_client.py
import json, socket, time, config

class Client:
    tcp_port = None
    s = None

    def __init__(self, tcp_port):
        self.tcp_port = tcp_port
        host = getattr(config, "TCP_HOST", None) or "127.0.0.1"   # 优先用 127.0.0.1
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # —— 新增：带退避的重试连接，小等 10 秒等 server 起好 ——
        deadline = time.time() + 10.0
        last_err = None
        while time.time() < deadline:
            try:
                self.s.connect((host, tcp_port))
                break
            except ConnectionRefusedError as e:
                last_err = e
                time.sleep(0.2)
        else:
            raise last_err

        print(self.s.recv(config.BUFFER_SIZE).decode())
        # self.s.send(json.dumps({'opt_type': 0}).encode())
        self.s.sendall(json.dumps({'opt_type': 0}).encode() + b'\n')

    def data_transfer(self, url: str, privacy_data: dict):
        print('Send Data')
        # payload = json.dumps({'opt_type': 1, 'url': url, 'data': privacy_data}).encode()
        # if len(payload) % config.BUFFER_SIZE == 0:
        #     payload += b' '
        # self.s.sendall(payload)
        # time.sleep(0.2)
        try:
            # 1. 序列化数据
            # ensure_ascii=False 可以让中文不转义，减小包体积且易读
            payload_dict = {'opt_type': 1, 'url': url, 'data': privacy_data}
            json_str = json.dumps(payload_dict, ensure_ascii=False)
            
            # ★★★ 核心修改 2: 必须在末尾追加换行符 \n ★★★
            # 这样接收端的 readline() 才能正确切分每一条数据
            payload = json_str.encode('utf-8') + b'\n'
            
            # ★ 修改 3: 移除之前的“补空格”逻辑
            # if len(payload) % config.BUFFER_SIZE == 0: ... (不再需要)
            
            # 2. 发送全量数据
            self.s.sendall(payload)
            
            # ★ 修改 4: 移除 sleep
            # 既然有了明确的分隔符 \n，接收端能自动处理粘包，不需要 sleep 来让步
            # time.sleep(0.2) 
            
        except Exception as e:
            print(f"[Client] Send Error: {e}")
            # 可以在这里做简单的重连尝试，或者直接忽略
    def close(self):
        # self.s.send(json.dumps({'opt_type': 2}).encode())
        self.s.sendall(json.dumps({'opt_type': 2}).encode() + b'\n')
        self.s.close()
