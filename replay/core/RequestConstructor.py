import itertools
import json
import os
import urllib.parse
# import sys

# # 添加新的路径
# sys.path.append('./replay')
from replay.lib.DB import DB
import replay.lib.Utils as Utility
from trafficMonitor import traffic_utils
def open_json_file(_path):
    with open(_path, 'r') as f:
        data = json.load(f)
    return data
import config
# 1. 加载受害者画像
VICTIM_PROFILE_PATH = os.path.join(config.project_prefix, "configs", "victim_profile.json")
VICTIM_DATA = {}

def load_victim_profile():
    global VICTIM_DATA
    if os.path.exists(VICTIM_PROFILE_PATH):
        try:
            with open(VICTIM_PROFILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get("enable"):
                    VICTIM_DATA = data.get("data", {})
                    print(f"[Config] 已加载受害者画像: {list(VICTIM_DATA.keys())}")
        except Exception as e:
            print(f"[Config] 受害者画像加载失败: {e}")

# 初始化时加载一次
load_victim_profile()

def get_victim_seeds(key):
    """
    根据参数名，利用 NLP/规则 匹配受害者画像中的值
    """
    if not VICTIM_DATA:
        return []
    
    # 1. 尝试直接 Key 匹配
    if key in VICTIM_DATA:
        return VICTIM_DATA[key]
    
    # 2. 尝试利用 traffic_utils 的分类能力进行语义匹配
    # judge_key 返回 (key, category)
    try:
        _, category = traffic_utils.judge_key(key)
        # 比如 key="patientId"，category 被识别为 "userid" 或 "user"
        # 那么我们就去 VICTIM_DATA 里找 "userid" 对应的值
        
        # 映射表：把 NLP 识别出的 category 映射到 profile.json 的 key
        # 你可以根据 traffic_utils.privacy_set 的定义来扩展这个映射
        category_map = {
            'userid': 'user_id', 'user': 'user_id', 'uid': 'user_id',
            'phone': 'phone', 'mobile': 'phone',
            'order': 'order_no', 'number': 'order_no',
            'idcard': 'id_card', 'citizen': 'id_card',
            'address': 'address_id',
            'username': ['userName', 'user_name'],
            'number': ['cardNo','cardno','CardNo']
        }
        target_key = category_map.get(category)
        if target_key and isinstance(target_key, list):
            # 处理多个可能的 key
            for k in target_key:
                if k in VICTIM_DATA:
                    return VICTIM_DATA[k]
        elif target_key and target_key in VICTIM_DATA:
            # print(f"  [Victim Match] param='{key}' -> category='{category}' -> victim='{target_key}'")
            return VICTIM_DATA[target_key]
            
    except Exception as e:
        pass
        
    return []

def get_header(_host):
    try:
        header_path = config.MINI_APP_LOG + "mitmproxy/{host}/header.json".format(host=_host)
        code = open_json_file(header_path)
        # print(code)
        header = code['request_header']
    except FileNotFoundError:
        header = None
        print("header.json not found")
    return header
# ★★★ 1. 定义黑名单：这些字段绝对不要改，改了必挂 ★★★
IGNORED_KEYS = {
    # 基础协议头
    'user-agent', 'user_agent', 'ua', 
    'content-type', 'accept', 'connection', 'host', 'referer', 'origin',
    'accept-encoding', 'accept-language','authorization','dataSource',
    # 认证与签名
    'sign', 'signature', 'token', 'access_token', 'auth', 'ticket', 'session', 'sessionid',
    # 时间戳与随机数
    'timestamp', 'ts', '_', 'nonce', 'salt','status',
    # 基础设施与追踪
    'version', 'v', 'platform', 'os', 'nettype', 'scene', 
    'sys_track_code', 'track_code', 'traceid', 'requestid','isDefault',
    # 业务无关
    'charset', 'lang', 'language','enterprise_id', 'hospital_id', 'resource_id','resource_code','operation_name','name','code'
}
TARGET_KEYS = {'user_id', 'userid', 'user_id', 'uid', 'account_id', 'accountid','user_name','username','cardno','cardNo','CardNo','phone','mobile','order_no','orderno','orderNo','id_card','idcard','citizen','address_id','addressId'}

def is_ignored(key):
    return key.lower() in IGNORED_KEYS

def is_target_key(k: str) -> bool:
    # 1. 先把 None 和 空字符串 拦住
    if not k: 
        return False
        
    # 2. 此时 k 肯定有值，放心调用 lower()
    if k.lower() in TARGET_KEYS:
        # print(f"  [Target Key] '{k}' 命中关键字段，进行变异") # 调试时可以打开
        return True
        
    return False
def get_seeds(key, current_val):
    """
    查询种子池，返回 [原始值, 受害者种子..., 数据库种子...]
    策略：
    1. 原始值必选。
    2. 受害者种子（Victim）最高优先级，且排在前面。
    3. 数据库种子（DB）做补充，且数量动态控制。
    """
    # 1. 初始化结果列表，始终包含原始值
    seed_list = [current_val]
    
    # 标记是否命中受害者画像
    hit_victim = False

    # ---------------------------------------------------------
    # 第一步：尝试注入“受害者账号” (High Priority)
    # ---------------------------------------------------------
    victim_seeds = get_victim_seeds(key) # 调用之前定义的 victim 逻辑
    if victim_seeds:
        for v in victim_seeds:
            # 【去重逻辑】排除原始值，且避免重复添加
            if str(v) != str(current_val) and v not in seed_list:
                seed_list.append(v)
                hit_victim = True
                # print(f"  [Inject Victim] 注入受害者数据: {key} -> {v}")

    # ---------------------------------------------------------
    # 第二步：从数据库补充挖掘到的种子 (Low Priority)
    # ---------------------------------------------------------
    try:
        _, category = traffic_utils.judge_key(key)
        if category:
            db = DB()
            # 从数据库拿一批种子 (比如数据库默认 limit 20)
            db_seeds = db.get_seeds_by_type(category, exclude_value=current_val)
            
            if db_seeds:
                
                # ★★★ 核心策略：动态控制数量 ★★★
                # 如果已经有了受害者种子，证明我们在做定向打击，数据库种子只需 2-3 个做混淆即可。
                # 如果没有受害者种子，证明我们在做盲测，需要多一点数据库种子 (比如 10 个) 来增加命中率。
                max_db_count = 3 if hit_victim else 10
                
                count = 0
                for s in db_seeds:
                    if count >= max_db_count:
                        break
                    
                    # 【去重逻辑】确保不重复添加受害者种子已经加过的值
                    if s not in seed_list:
                        seed_list.append(s)
                        count += 1
                        
    except Exception as e:
        # print(f"Get seeds error: {e}")
        pass
        
    return seed_list

def mutate_recursive(data, key_context=None):
    """
    递归变异核心逻辑
    :param data: 当前要处理的数据 (dict, list, str, int...)
    :param key_context: 当前数据的键名 (用于判断是否 ignored 或 seed 类型)
    :return: 变异后的数据列表 [data_variant_1, data_variant_2, ...]
    """
    # 1. 基础情况：如果是 None，直接返回
    if data is None:
        return [None]

    # 2. 检查黑名单 (仅针对叶子节点或字符串)
    if key_context and is_ignored(key_context):
        # print(f"  [Ignored Key] '{key_context}' 在黑名单中，跳过变异")
        return [data]
    allow_mutate = is_target_key(key_context)
    # if key_context and key_context.lower() in TARGET_KEYS:
    #     print(f"  [Target Key] '{key_context}' 命中关键字段，进行变异")


    # 3. 处理 字典 (Dict)
    if isinstance(data, dict):
        # 笛卡尔积组合字典的每个字段
        # 注意：为了防止爆炸，建议每次只变异一个字段 (One-change strategy)，
        # 但这里为了简单，我们先收集所有字段的变异，然后组合。
        
        keys = list(data.keys())
        field_mutations = {} # {key: [val1, val2]}
        
        for k, v in data.items():
            field_mutations[k] = mutate_recursive(v, key_context=k)
        
        # 组合 (为了防止组合爆炸，如果总数太多，就强制只取前 20 个组合)
        combinations = list(itertools.product(*field_mutations.values()))
        if len(combinations) > 20: 
            combinations = combinations[:10] # 剪枝
            
        results = []
        for combo in combinations:
            new_dict = {}
            for i, k in enumerate(keys):
                new_dict[k] = combo[i]
            results.append(new_dict)
        return results

    # 4. 处理 列表 (List)
    if isinstance(data, list):
        # 简化处理：只变异列表里的第一个元素，或者保持原样
        # 列表的笛卡尔积太复杂，这里采取保守策略
        if not data: return [[]]
        
        # 尝试变异每个元素，但只组合“全部原始”和“单个变异”
        # 这里简化：不做变异，直接返回原列表 (TODO: 以后增强)
        return [data] 

    # 5. 处理 字符串 (String) - 核心逻辑！
    if isinstance(data, str):

        # A. 尝试判断是否是 JSON 字符串 (如 body_content)
        stripped = data.strip()
        if (stripped.startswith('{') and stripped.endswith('}')) or \
           (stripped.startswith('[') and stripped.endswith(']')):
            try:
                # 解包
                inner_obj = json.loads(data)
                # 递归变异内部对象
                inner_mutations = mutate_recursive(inner_obj, key_context)
                # 重新打包回字符串
                return [json.dumps(obj, ensure_ascii=False) for obj in inner_mutations]
            except:
                pass # 解析失败，当做普通字符串处理
        if not allow_mutate:
            return [data]
        print(f"[Mutate] 处理 Key: '{key_context}' 类型: {type(data).__name__}")
        # B. 种子替换 (Seed Replacement)
        seeds = get_seeds(key_context, data)
        if len(seeds) > 1:
            return seeds
        # ★★★ 核心修改：白名单强校验 ★★★
        # 只有纯数字且长度适中才变异
        # if data.isdigit() and len(data) < 20:
        if data.isdigit():
            return Utility.generate_sequence(data, 1, 5) # 范围小一点
            
        return [data]

    # 6. 处理 数字 (Int/Float)
    if isinstance(data, (int, float)):
        # ★★★ 修复：数字也必须受白名单控制 ★★★
        if not allow_mutate:
            return [data]
        return Utility.generate_sequence(data, 1, 5)

    return [data]


def build_params(_params, start_index=1, end_index=20):
    """
    入口函数
    """
    try:
        # 解析最外层 JSON
        if isinstance(_params, str):
            root_data = json.loads(_params)
        else:
            root_data = _params
            
        # 调用递归变异
        # root_data 是个 dict，进入递归逻辑
        mutated_list = mutate_recursive(root_data)
        
        # 去重并返回
        # 由于 dict 不可哈希，手动去重比较麻烦，这里利用 json 串去重
        unique_results = []
        seen = set()
        
        # 始终包含原始值 (mutate_recursive 的逻辑通常已经包含了，但做个双保险)
        # origin_json = json.dumps(root_data, sort_keys=True)
        # seen.add(origin_json)
        # unique_results.append(root_data)
        
        for item in mutated_list:
            item_json = json.dumps(item, sort_keys=True)
            if item_json not in seen:
                seen.add(item_json)
                unique_results.append(item)
                
        return unique_results

    except Exception as e:
        print(f"[BuildParams Error] {e}")
        return []

def build_url(_url, _params, start_index=1, end_index=10):
    tmp_url = []
    g_url_root = _url.split('?')[0]
    gen_params = build_params(_params, start_index, end_index)
    # for para_item in gen_params:
    #     tmp_url.append(g_url_root + "?" + urllib.parse.urlencode(para_item))
    # return tmp_url

    for para_dict in gen_params:
        # urlencode 需要扁平字典，如果里面有嵌套 dict，urllib 处理不好
        # 但通常 GET 请求不应该有深层嵌套 JSON，如果有，通常也是 string 格式
        # 这里尝试转换
        try:
            # 将 dict 中的非字符串值转为 json 串，以防万一
            flat_dict = {}
            for k, v in para_dict.items():
                if isinstance(v, (dict, list)):
                    flat_dict[k] = json.dumps(v, ensure_ascii=False)
                else:
                    flat_dict[k] = str(v)
            tmp_url.append(g_url_root + "?" + urllib.parse.urlencode(flat_dict))
        except:
            pass
            
    return tmp_url

# 补充需要的 get_header (保持你原有的逻辑)
def open_json_file(_path):
    with open(_path, 'r', encoding='utf-8') as f:
        return json.load(f)