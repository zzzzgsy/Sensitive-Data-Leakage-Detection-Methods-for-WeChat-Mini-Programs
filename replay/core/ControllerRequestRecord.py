import os
import time

from replay.lib.DB import DB
from replay.lib import Utils as Utility
import config
class ControllerRequestRecord:
    # init
    db = DB()
    timestamp = str(int(time.mktime(time.localtime(time.time()))))

    def query_record_fusion(self, _host, _content_type='json', _method='get'):
        sql = ("select distinct(a.url) as origin_url,a.referer,b.url as gen_url,b.response_hash,b.response"
               " from request_record a left join request_record_second as b on a.url=b.origin_url"
               " where a.host='{host}' and a.content_type='{content_type}' and a.method='{method}'"
               " and a.get_sensitive!='' and  b.url!='' and b.response not in('[]','')").format(host=_host, content_type=_content_type,
                                                                                                method=_method)
        # print(sql)
        return self.db.query(sql)

    def query_record_second_analysis(self, _host):
        sql = ("select host,method,origin_url,referer,url,gen_params,response_hash,"
               "response_sensitive,response_exists_sensitive,response from request_record_second "
               "group by response_hash HAVING response_exists_sensitive>0 and "
               "host like '%{host}%' order by referer desc,origin_url desc ,url desc").format(host=_host)
        rs = self.db.query(sql)
        return Utility.build_tree(rs)

    def query_record_second(self, where='1=1', fields="*"):
        return self.db.query_request_record_second(where=where, fields=fields)

    def add_request_record_second(self, _data):
        # API Fingerprint
        hash_val = Utility.md5(_data['method'] + _data['gen_params'] + _data['response'])
        add_data_str = ("'{host}','{hash}','{method}','{content_type}',"
                        "'{referer}','{origin_url}',"
                        "'{url}','{response}','{response_exists_sensitive}',"
                        "'{response_sensitive}','{response_hash}','{gen_params}','{timestamp}'")
        add_data = add_data_str.format(host=_data['host'], hash=hash_val, method=_data['method'], content_type=_data['content_type'],
                                       referer=_data['referer'], origin_url=_data['origin_url'],
                                       url=_data['url'], response=_data['response'],
                                       response_exists_sensitive=_data['response_exists_sensitive'],
                                       response_sensitive=_data['response_sensitive'],
                                       response_hash=Utility.md5(_data['response']), gen_params=_data['gen_params'],
                                       timestamp=self.timestamp)
        record_check = self.query_record_second(where="hash='{hash_val}'".format(hash_val=hash_val), fields='id')
        print("record_check===>", len(record_check))
        if len(record_check) == 0:
            # print(add_data_str)
            try:
                self.db.add_request_record_second(values=add_data)
            except Exception as e:
                print("Exception:", str(e))
                dir_path = config.MINI_APP_LOG + "mitmproxy/" + _data['host'] + "/error/"
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                path = _data['url'].split("/")[-1]
                path = path.split("?")[0]
                path = path.replace(".", "_")
                file_path = dir_path + path + "_error.txt"
                w_data = {
                    "exception:": str(e),
                    "url": _data['url'],
                    "data_str": add_data_str,
                    "create_time": self.timestamp
                }
                with open(file_path, mode='a+', encoding="utf-8") as f:
                    f.write(Utility.dict2json(w_data))

    def query_record(self, where, fields="*"):
        return self.db.query_request_record(where=where, fields=fields)

    def add_record(self, _data):
        # API Fingerprint
        hash_val = Utility.md5(_data['method'] + _data['url'] + _data['response'])
        # print(_data['response'])
        # ★★★ 修复：使用 ? 占位符，而不是 format 拼接 ★★★
        sql = '''INSERT INTO request_record (
            flow_id, host, port, hash, method, url, referer, content_type,
            response, response_exists_sensitive, response_sensitive,
            path, path_exist_sensitive, path_sensitive,
            get_params, get_exist_sensitive, get_sensitive,
            post_params, post_exist_sensitive, post_sensitive, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''
        
        # 准备参数元组
        params = (
            _data['flow_id'], _data['host'], _data['port'], hash_val,
            _data['method'], _data['url'], _data['referer'],
            _data['content_type'], _data['response'], 
            _data['response_exists_sensitive'], _data['response_sensitive'],
            _data['path'], _data['path_exist_sensitive'], _data['path_sensitive'],
            _data['get_params'], _data['get_exist_sensitive'], _data['get_sensitive'],
            _data['post_params'], _data['post_exist_sensitive'], _data['post_sensitive'],
            self.timestamp
        )
        
        # 检查是否存在
        record_check = self.db.query(f"SELECT id FROM request_record WHERE hash='{hash_val}'")
        
        if len(record_check) == 0:
            try:
                # 传入 params
                self.db.execute(sql, params)
                # print(f"Inserted: {_data['url']}")
            except Exception as e:
                print(f"[Controller] Add Record Error: {e}")