
import time
import os, urllib.request

# 1) 清理代理环境变量
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
        "http_proxy","https_proxy","all_proxy","no_proxy","proxy","PROXY"):
    os.environ.pop(k, None)

# 2) 告诉 urllib / requests 不用系统代理
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

try:
    import requests
    requests.sessions.Session.trust_env = False
except Exception:
    pass

urllib.request.getproxies = (lambda: {})
import dashscope
import base64
import json
from dashscope import MultiModalConversation

# 配置你的 API Key
dashscope.api_key = "sk-9fe6da7194474c61b8bb916e11c9eeec"  # 替换为你的实际 API Key
import os
import json
import base64
from openai import OpenAI
# ==========================================
# 🚀 极限优化点 2：裁剪无效 OCR 数据与键名压缩
# ==========================================
def clean_ocr_data(ocr_obj):
    """
    极限裁剪 OCR 数据：
    1. 彻底丢弃 score、polygon 等无关大模型决策的字段。
    2. 将输入的 Key 压缩为 t, b, xy，进一步榨干 Token 水分！
    """
    cleaned_list = []
    if isinstance(ocr_obj, list):
        for item in ocr_obj:
            clean_item = {}
            if 'text' in item: 
                clean_item['t'] = item['text']       # 用 t 代替 text
            if 'bbox' in item: 
                clean_item['b'] = item['bbox']       # 用 b 代替 bbox
            if 'click_xy' in item: 
                clean_item['xy'] = item['click_xy']  # 用 xy 代替 click_xy
            # 注意：根本不提取 'score'，它会被直接遗弃！
            cleaned_list.append(clean_item)
        return cleaned_list
    return ocr_obj
def timeit(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        print(f"{func.__name__} took {time.perf_counter()-start:.2f}s")
        return result
    return wrapper


from PIL import Image
import os, urllib.request
import json
import base64
import io

# ==========================================
# 🚀 核心优化点 1：图像极限压缩引擎
# ==========================================
def compress_image_to_base64(image_path, max_width=480, quality=50):
    """
    压缩图片并转换为 base64 字符串。
    将 PNG 强转为高压缩率的 JPEG，并限制最大宽度。
    大幅降低网络 Upload 耗时与大模型视觉算子开销。
    """
    with Image.open(image_path) as img:
        # 1. 强转 RGB 模式（丢弃透明通道，不仅减小体积，且 JPEG 必须为 RGB）
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # 2. 限制分辨率：宽度超过 max_width 则等比例缩放
        width, height = img.size
        if width > max_width:
            new_height = int(max_width * height / width)
            # 使用 LANCZOS 降采样保证图标依然清晰
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            
        # 3. 内存中存为高压缩 JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

# ==========================================
# 🚀 核心优化点 2：Token 极简化
# ==========================================
def prepare_data_for_api_call(image_path, ocr_json_path):
    """准备调用 API 所需的数据"""
    # 使用压缩函数替代原有的裸转 base64
    image_b64 = compress_image_to_base64(image_path)
    
    # 加载 OCR 数据并进行极限序列化（去除所有多余空格，极大节省 Token）
    with open(ocr_json_path, 'r', encoding='utf-8') as file:
        ocr_obj = json.load(file)
        # 裁剪无用数据
        ocr_obj = clean_ocr_data(ocr_obj)
        ocr_compact_str = json.dumps(ocr_obj, ensure_ascii=False, separators=(',', ':'))
        
    return image_b64, ocr_compact_str


# def prepare_data_for_api_call(image_path, ocr_json_path):
#     """
#     准备调用 API 所需的数据：包括将图片转换为 Base64 编码和加载 OCR 数据。
    
#     Args:
#         image_path (str): 图片文件的本地路径。
#         ocr_json_path (str): OCR 数据的 JSON 文件路径。
        
#     Returns:
#         tuple: 包含图片 Base64 编码字符串和 OCR 数据的元组。
#     """
#     # 将图片转换为 Base64
#     image_b64 = image_to_base64(image_path)
    
#     # 加载 OCR 数据
#     ocr_data = load_ocr_data(ocr_json_path)
#     return image_b64, ocr_data
# 初始化 OpenAI 客户端（方舟接入点）
client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=os.getenv("ARK_API_KEY", "")  # 设置密钥
)

def call_qwen_vl_for_interactive_elements(image_path, ocr_json_path):
    """
    调用豆包多模态模型分析小程序页面，提取可交互控件
    （替换原 DashScope 调用，使用 OpenAI 客户端 + 豆包模型）
    """
    try:
        # 1. 准备图片 Base64 和 OCR 数据
        image_b64, ocr_data = prepare_data_for_api_call(image_path, ocr_json_path)
    except Exception as e:
        raise Exception(f"数据准备失败: {e}")

    # 2. 构建 Prompt（完全保留原逻辑）
    prompt_text = f"""
你是一名 **移动应用安全分析与隐私合规专家**。你将接收一张医疗类小程序截图和 OCR 数据(包含文字、bbox、click_xy 等原始数据)。
你的核心任务是：**识别页面中可能涉及“敏感数据访问”、“权限操作”或“越权风险”的关键入口。**
# 【任务目标】
请结合视觉信息（截图）和文字信息（OCR），从页面中提取 **高风险交互元素**，并按风险等级排序。
# 【识别标准：什么是敏感/高风险入口？】
1. **tarbar与账户**：
   - 入口词：登录、注册、个人中心、我的、认证、就诊人、绑定、切换账号、成员、地址、设置、管理。
   - 视觉特征：人像图标、头像区域。
2. **关键操作与可能共享信息的操作（比如他人评价、他人发言、他人记录等）**：
   - 入口词：问诊、挂号、医生、医生评价、评价、查看、收藏医生。
3. **敏感记录与订单**：
   - 入口词：订单、挂号记录、缴费记录、报告查询、体检报告、处方、病例、钱包、流水。
   - 视觉特征：票据图标、列表入口。
4. **关键业务操作**：
   - 入口词：支付、充值、申请、预约、查询、确认、提交、授权、允许。
   - 视觉特征：底部醒目的大按钮（通常是 Primary Color）。

# 【过滤规则】
- 忽略纯展示文本（如广告语、欢迎词）。
- 忽略无关紧要的功能（如“清理缓存”、“关于我们”、“常见问题”），除非页面除此之外无其他入口。
- 忽略底部版权信息。
# 【输入数据（OCR）】
说明：输入的 JSON 格式为 {{"t":"文字", "b":[bbox坐标], "xy":[点击中心点]}}
{ocr_data}
# 【输出要求】
请输出一个 **JSON 数组**，数组中每个对象包含以下字段：
- "text": 控件文字（对控件最核心的交互含义命名，可从 OCR 自动纠错，但不能胡乱臆造。若无文字，描述其功能，如“个人中心图标”）。
- "bbox": [xmin, ymin, xmax, ymax]（优先复用 OCR 数据，若 OCR 缺失则根据截图布局合理估算）。
- "click_xy": [x, y]（点击中心点，优先复用 OCR 数据，若 OCR 缺失则根据截图布局合理估算）。
- "risk_level": "high" | "medium" | "low" （**新增字段**：根据上述标准判断风险等级）。
- "semantic": "auth" | "order" | "pay" | "profile" | "other" （**新增字段**：语义标签）。
# 【排序策略】
1. Risk Level 为 "high" 的排在最前面。
2. 其次是 "medium"。
3. 仅输出 **Top 10** 最关键的入口（最多输出10个）
# 【输出示例】
[
  {{"text": "查看体检报告", "bbox": [20, 100, 200, 150], "click_xy": [110, 125], "risk_level": "high", "semantic": "order"}},
  {{"text": "个人中心", "bbox": [300, 50, 350, 100], "click_xy": [325, 75], "risk_level": "high", "semantic": "profile"}}
]
*** 请直接返回 JSON 数组，严禁包含 Markdown 格式（如 ```json ... ```）或任何解释性文字。***
"""

    # 3. 构造多模态消息（使用 Data URL 传递本地图片）
    # 确定图片 MIME 类型（简单根据扩展名判断，可扩展）
    mime_type = "image/png" if image_path.lower().endswith('.png') else "image/jpeg"
    data_url = f"data:{mime_type};base64,{image_b64}"

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_url}
                },
                {
                    "type": "text",
                    "text": prompt_text
                }
            ]
        }
    ]
    # print(messages)
    # 4. 调用豆包模型
    try:
        completion = client.chat.completions.create(
            model="doubao-seed-1-6-lite-251015",  # 方舟推理接入点 ID
            messages=messages,
            temperature=0.1,   # 降低随机性
            # seed=12345       # OpenAI 接口可能不支持 seed，可省略
            max_tokens=800,
            reasoning_effort="minimal"
        )
    except Exception as e:
        raise Exception(f"API 调用失败: {e}")

    # 5. 提取回复文本
    reply_text = completion.choices[0].message.content
    if not reply_text:
        raise ValueError("模型返回空内容")
    # print(f"模型原始回复：\n{reply_text}")

    # 6. 尝试解析 JSON（兼容可能出现的 Markdown 代码块）
    try:
        result = json.loads(reply_text)
    except json.JSONDecodeError:
        # 尝试提取 ```json ... ``` 中的内容
        import re
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', reply_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                raise ValueError(f"提取的 JSON 解析失败: {e}")
        else:
            raise ValueError(f"模型未返回有效 JSON，原始回复：\n{reply_text}")

    return result

# ======================
# 使用示例
# ======================
if __name__ == "__main__":
    image_file = r"G:\miniapp\XPOScope-main\dynamicExerciser\data\screenshots\1.png"
    ocr_json_path = r"G:\miniapp\XPOScope-main\dynamicExerciser\data\page_text\ocr_raw_1.json"
    try:
        interactive_elements = call_qwen_vl_for_interactive_elements(image_file, ocr_json_path)
        print("✅ 提取到的可交互控件：")
        print(json.dumps(interactive_elements, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"❌ 错误: {e}")