import json
import replay.core.Config as Config

import sqlite3
import os
import config
DB_PATH = os.path.join(config.MINI_APP_LOG, "scan_data_origin.db")
class DB:
    def __init__(self):
        # 使用项目统一的数据库路径
        self.db_path = os.path.join(config.MINI_APP_LOG, "scan_data_origin.db")
        self._init_tables()

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_tables(self):
        """初始化第①套代码需要的复杂表结构"""
        conn = self.get_conn()
        c = conn.cursor()

        # 1. 流量表：存储所有抓到的 HTTP 请求
        c.execute('''CREATE TABLE IF NOT EXISTS traffic (
        req_id TEXT PRIMARY KEY,
        host TEXT,
        url TEXT,
        method TEXT,
        req_headers TEXT,
        req_params TEXT,
        req_body TEXT,
        resp_status INTEGER,
        resp_body TEXT,
        ts REAL,
        mini_app_name TEXT
    )''')
        # 2. 种子池表：存储挖掘到的敏感信息 (为越权测试做准备)
        c.execute('''CREATE TABLE IF NOT EXISTS seeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seed_type TEXT,  -- e.g., "user_id", "order_no", "phone"
            value TEXT,
            source_url TEXT,
            mini_app_name TEXT,
            UNIQUE(seed_type, value) -- 避免重复存储同一个ID
        )''')


                
        # 表1: request_record (存储原始抓包经过 Analysis 后的数据)
        c.execute('''CREATE TABLE IF NOT EXISTS request_record (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flow_id TEXT,
            host TEXT,
            port INTEGER,
            hash TEXT,
            method TEXT,
            url TEXT,
            referer TEXT,
            content_type TEXT,
            response TEXT,
            response_exists_sensitive INTEGER,
            response_sensitive TEXT,
            path TEXT,
            path_exist_sensitive INTEGER,
            path_sensitive TEXT,
            get_params TEXT,
            get_exist_sensitive INTEGER,
            get_sensitive TEXT,
            post_params TEXT,
            post_exist_sensitive INTEGER,
            post_sensitive TEXT,
            timestamp TEXT
        )''')

        # 表2: request_record_second (存储重放/二阶请求产生的数据)
        c.execute('''CREATE TABLE IF NOT EXISTS request_record_second (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT,
            hash TEXT,
            method TEXT,
            content_type TEXT,
            referer TEXT,
            origin_url TEXT,
            url TEXT,
            response TEXT,
            response_exists_sensitive INTEGER,
            response_sensitive TEXT,
            response_hash TEXT,
            gen_params TEXT,
            timestamp TEXT
        )''')

        
        conn.commit()
        conn.close()

    def query(self, sql,params=None):
        """执行原生 SQL 查询，返回字典列表"""
        conn = self.get_conn()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            # 支持参数
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            rows = cursor.fetchall()
            # 转为普通 dict 列表
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[DB] Query Error: {e} \nSQL: {sql}")
            return []
        finally:
            conn.close()

    # def execute(self, sql,params=None):
    #     conn = self.get_conn()
    #     try:
    #         # ★★★ 修复：支持 params 参数 ★★★
    #         if params:
    #             conn.execute(sql, params)
    #         else:
    #             conn.execute(sql)
    #         conn.commit()
    #     except Exception as e:
    #         print(f"[DB] Execute Error: {e}")
    #     finally:
    #         conn.close()

    def execute(self, sql, params=None):
        conn = self.get_conn()
        try:
            if params:
                conn.execute(sql, params)
            else:
                conn.execute(sql)
            conn.commit()
        except Exception as e:
            # ★★★ 关键修复：除了打印日志，必须把异常抛出去！
            # 这样 save_traffic 才能捕获 IntegrityError
            # print(f"[DB] Execute Error: {e} | SQL: {sql[:50]}...")
            raise e 
        finally:
            conn.close()


    def clear_tables(self):
            """清空分析用的两张表，防止脏数据干扰"""
            print("[DB] Cleaning old records...")
            try:
                self.execute("DELETE FROM request_record")
                self.execute("DELETE FROM request_record_second")
                self.execute("DELETE FROM traffic")
                self.execute("DELETE FROM seeds")
                # 重置自增 ID
                self.execute("DELETE FROM sqlite_sequence WHERE name='request_record'")
                self.execute("DELETE FROM sqlite_sequence WHERE name='request_record_second'")
                self.execute("DELETE FROM sqlite_sequence WHERE name='traffic'")
                self.execute("DELETE FROM sqlite_sequence WHERE name='seeds'")
            except Exception as e:
                print(f"[DB] Clean warning: {e}")
    # --- 适配 ControllerRequestRecord 的专用方法 ---

    def add_request_record(self, values):
        # values 应该是一个格式化好的字符串，包含所有字段的值
        # 注意：这种拼接 SQL 的方式有注入风险，但在毕设内网环境通常可接受
        # 为了兼容你原来的代码逻辑 (ControllerRequestRecord 传进来的是 'val1','val2'...)
        sql = f'''INSERT INTO request_record (
            flow_id, host, port, hash, method, url, referer, content_type,
            response, response_exists_sensitive, response_sensitive,
            path, path_exist_sensitive, path_sensitive,
            get_params, get_exist_sensitive, get_sensitive,
            post_params, post_exist_sensitive, post_sensitive, timestamp
        ) VALUES ({values})'''
        self.execute(sql)

    def add_request_record_second(self, values):
        sql = f'''INSERT INTO request_record_second (
            host, hash, method, content_type, referer, origin_url,
            url, response, response_exists_sensitive,
            response_sensitive, response_hash, gen_params, timestamp
        ) VALUES ({values})'''
        self.execute(sql)

    def query_request_record(self, where="1=1", fields="*"):
        sql = f"SELECT {fields} FROM request_record WHERE {where}"
        return self.query(sql)

    def query_request_record_second(self, where="1=1", fields="*"):
        sql = f"SELECT {fields} FROM request_record_second WHERE {where}"
        return self.query(sql)

    def save_traffic(self, mini_app_name, flow_data):
        # conn = sqlite3.connect(DB_PATH)
        # c = conn.cursor()
        print("[DB] Saving traffic...")
        meta = flow_data.get("__meta", {})
        req_id = meta.get("req_id", "")
        if not req_id: 
            print("[DB] skip: no req_id, meta=", meta)
            return # 没有ID的无法处理

        direction = meta.get("dir", "").lower() # req 或 resp
        ts = meta.get("ts", 0.0)
        url = meta.get("url", "") or flow_data.get("url", "")
        
        # 提取 Host
        from urllib.parse import urlparse
        try:
            host = urlparse(url).hostname
        except:
            host = ""

        # 1. 尝试插入新行 (如果 req_id 已存在则会报错，进入 except)
        try:
            print(f"[DB] Inserting new traffic req_id: {req_id} | dir: {direction}")
            if direction == "req":
                method = meta.get("method", "")
                req_headers = json.dumps(flow_data.get("headers", {}), ensure_ascii=False)
                # 这里简化处理，把整个包体视为 params/body，你可以根据实际需求细分
                req_params = json.dumps(flow_data, ensure_ascii=False)
                
                self.execute('''INSERT INTO traffic (req_id, host, url, method, req_headers, req_params, ts, mini_app_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (req_id, host, url, method, req_headers, req_params, ts, mini_app_name))
            
            elif direction == "resp":
                status = meta.get("status", 0)
                # 响应体通常在 data 字段里，或者整个 flow_data
                resp_body = json.dumps(flow_data, ensure_ascii=False)
                
                self.execute('''INSERT INTO traffic (req_id, host, url, resp_status, resp_body, ts, mini_app_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (req_id, host, url, status, resp_body, ts, mini_app_name))
                
        except sqlite3.IntegrityError:
            # 2. 如果 ID 已存在（说明另一半已经存了），则执行 UPDATE
            if direction == "req":
                print("[DB] Updating existing req_id:", req_id)
                method = meta.get("method", "")
                req_headers = json.dumps(flow_data.get("headers", {}), ensure_ascii=False)
                req_params = json.dumps(flow_data, ensure_ascii=False)
                self.execute('''UPDATE traffic SET 
                            host=?, url=?, method=?, req_headers=?, req_params=?, ts=?
                            WHERE req_id=?''',
                        (host, url, method, req_headers, req_params, ts, req_id))
            
            elif direction == "resp":
                print("[DB] Updating existing resp for req_id:", req_id)
                status = meta.get("status", 0)
                resp_body = json.dumps(flow_data, ensure_ascii=False)
                self.execute('''UPDATE traffic SET 
                            resp_status=?, resp_body=? 
                            WHERE req_id=?''',
                        (status, resp_body, req_id))

    # 用于收集种子（后续在 Harvester 模块调用）
    def save_seed(self, seed_type, value, source_url, app_name):
        # conn = sqlite3.connect(DB_PATH)
        # c = conn.cursor()
        if not value or len(str(value)) < 2: return # 过滤太短的垃圾数据
        try:
            self.execute("INSERT OR IGNORE INTO seeds (seed_type, value, source_url, mini_app_name) VALUES (?, ?, ?, ?)",
                    (seed_type, value, source_url, app_name))
            # self.execute("INSERT OR IGNORE INTO seeds (seed_type, value, source_url) VALUES (?, ?, ?)", (category, str(value), source_url))
        except Exception as e:
            print(f"[DB] Save seed failed: {e}")
        # conn.close()

    #     # ★★★ 新增：插入种子 ★★★
    # def add_seed(self, category, value, source_url):

    # ★★★ 新增：获取某种类型的种子（用于替换）★★★
    def get_seeds_by_type(self, seed_type, exclude_value=None):
        sql = f"SELECT value FROM seeds WHERE seed_type = '{seed_type}'"
        if exclude_value:
            sql += f" AND value != '{exclude_value}'"
        # 限制取前 20 个，避免攻击请求过多
        sql += " LIMIT 20"
        
        res = self.query(sql)
        return [r['value'] for r in res]




def check_empty_collection(_collection):
    return '' if len(_collection) == 0 else _collection


def check_host(_host):
    _host = str(_host).lower()
    flag = False
    for host in Config.hosts:
        if host in _host:
            flag = True
            break
    return flag


def check_method(_method):
    return str(_method).lower() in Config.methods


def check_accept(_accept):
    _accept = str(_accept).lower()
    flag = False
    for t_a in Config.accepts:
        if t_a in _accept:
            flag = True
            break
    return flag


def check_response_content_type(_content_type):
    _content_type = str(_content_type).lower()
    flag = False
    for t_a in Config.response_type:
        if t_a in _content_type:
            flag = True
            break
    return flag


def check_question_mark(_path):
    return "?" in _path


def check_is_json(_str):
    try:
        json.loads(_str)
        return True if _str.replace(" ", "") != "[]" and _str.replace(" ", "") != "{}" else False
    except ValueError:
        return False


def check_is_html(_str):
    return 'text/html' in _str