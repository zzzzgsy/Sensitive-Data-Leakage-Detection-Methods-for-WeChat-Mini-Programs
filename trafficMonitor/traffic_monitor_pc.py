import asyncio
import time
import urllib.parse as up
from mitmproxy import http
from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster
import config
import traffic_utils
import traffic_transfer_client_pc

# ----------------- 只抓“微信 PC 小程序”流量的判定 -----------------
WECHAT_PC_MARKERS = (
    "servicewechat.com",
    "weixin.qq.com","mp.weixin.qq.com",
    "wx.qq.com","wxapp", "weapp","miniprogram","app_id","appid",
    # ★★★ 新增特征 ★★★
    "micromessenger", "windowswechat"
    )

def _is_wechat_traffic(flow: http.HTTPFlow) -> bool:
    """主机、路径、Referer 任意一个命中特征即可"""
    try:
        host = (flow.request.host or "").lower()
        path = (flow.request.path or "").lower()
        referer = (flow.request.headers.get("referer", "") or "").lower()
        # print( host, path, referer)
        # ★★★ 新增：获取 User-Agent ★★★
        ua = (flow.request.headers.get("user-agent", "") or "").lower()
    except Exception:
        return False

    return (
        any(m in host for m in WECHAT_PC_MARKERS)
        or any(m in path for m in WECHAT_PC_MARKERS)
        or any(m in referer for m in WECHAT_PC_MARKERS)
        # ★★★ 新增：检查 User-Agent ★★★
        or any(m in ua for m in WECHAT_PC_MARKERS)
    )


# ----------------- 常用小工具 -----------------
# def _is_image_url(url: str) -> bool:
#     u = (url or "").lower()
#     return u.endswith((".bmp", ".jpg", ".jpeg", ".png", ".gif", ".webp"))
import os, urllib.parse as up
# _IMG_EXTS = {".bmp",".jpg",".jpeg",".png",".gif",".webp",".avif",".svg"}
_IMG_EXTS = {".bmp", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg",".css",".js",".ico",".woff",".woff2",".ttf",".eot"}

def _is_image_url(url: str) -> bool:
    try:
        path = up.urlparse(url).path  # 只取路径部分，不包含 ?query
        ext = os.path.splitext(path)[1].lower()
        return ext in _IMG_EXTS
    except Exception:
        return False
    
def _is_textual(ct: str) -> bool:
    if not ct:
        return False
    ct = ct.lower()
    return ("json" in ct) or ("text" in ct) or ("xml" in ct) or ("x-www-form-urlencoded" in ct)

def _safe_to_dict(text: str):
    """用你项目里的 traffic_utils.to_dict 解析，不抛异常"""
    try:
        return traffic_utils.to_dict(text)
    except Exception:
        return None

def _parse_query(url: str) -> dict:
    q = up.urlparse(url).query
    if not q:
        return {}
    out = {}
    for k, vals in up.parse_qs(q, keep_blank_values=True).items():
        out[k] = vals[0] if len(vals) == 1 else vals
    return out

def _extract_sensitive_headers(headers: http.Headers) -> dict:
    """只摘取可能含凭证/可关联内容的头，避免把整堆 headers 都塞过去"""
    h = {k.lower(): v for k, v in headers.items(multi=False)}
    out = {}
    for key in ("authorization", "cookie", "x-token", "x-auth-token", "x-csrf-token", "referer", "user-agent"):
        if key in h and h[key]:
            out[key] = h[key]
    return out



# ----------------- Request/Response 结构化提取 -----------------
def _build_req_payload(flow: http.HTTPFlow) -> dict:
    req = flow.request
    payload = {}

    # 1) query
    payload.update(_parse_query(req.url))

    # 2) body
    ct = req.headers.get("Content-Type", "")
    body_text = None
    if _is_textual(ct):
        with contextlib.suppress(Exception):
            body_text = req.get_text()
    if body_text:
        js = _safe_to_dict(body_text)
        if isinstance(js, dict) and js:
            payload.update(js)
        elif "x-www-form-urlencoded" in ct.lower():
            for k, vals in up.parse_qs(body_text, keep_blank_values=True).items():
                payload[k] = vals[0] if len(vals) == 1 else vals

    # 3) headers（可能含凭证的）
    payload.update(_extract_sensitive_headers(req.headers))

    ts_req = getattr(req, "timestamp_start", time.time())
    payload["__meta"] = {
        "method": req.method,
        "ts": ts_req,
        "dir": "req",
        "req_id": flow.id,               # ★会话ID
        "url": req.url,                  # ★原始URL
    }
    return payload

def _build_resp_payload(flow: http.HTTPFlow) -> dict:
    res = flow.response
    ct = res.headers.get("Content-Type", "") or res.headers.get("content-type", "")
    if not _is_textual(ct):
        return {}

    with contextlib.suppress(Exception):
        text = res.get_text()
    if not text:
        return {}

    js = _safe_to_dict(text)
    if not isinstance(js, dict):
        # 顶层数组就先跳过，有需求再扩展
        return {}

    data = js.get("data")
    payload = dict(data) if isinstance(data, dict) and data else dict(js)

    ts_resp = getattr(res, "timestamp_start", time.time())
    payload["__meta"] = {
        "status": res.status_code,
        "ts": ts_resp,
        "dir": "resp",
        "req_id": flow.id,               # ★会话ID
        "url": flow.request.url,         # ★原始URL
    }
    return payload



async def start(client, m):
    my_addon = TrafficMonitor(client)
    m.addons.add(my_addon)
    await m.run()
    return m


class TrafficMonitor:
    url_list = None
    count = None
    client = None

    def __init__(self, client):
        self.url_list = []
        self.count = 0
        self.client = client
        pass
    
    def request(self, flow: http.HTTPFlow):
        if not _is_wechat_traffic(flow):
            return
        if flow.request.method not in ("GET","POST","PUT","PATCH"):
            return
        if _is_image_url(flow.request.url) or flow.request.url.lower().endswith(".js"):
            return
        payload = _build_req_payload(flow)
        if payload:
            self.client.data_transfer(flow.request.url, payload)

    def response(self, flow: http.HTTPFlow):
        if not _is_wechat_traffic(flow):
            return
        if flow.request.method not in ("GET","POST","PUT","PATCH"):
            return
        if flow.response.status_code != 200:
            return
        if _is_image_url(flow.request.url) or flow.request.url.lower().endswith(".js"):
            return
        payload = _build_resp_payload(flow)
        if payload:
            self.client.data_transfer(flow.request.url, payload)


import asyncio, contextlib
async def main(client):
    # ip = config.get_ip()
    # print(ip)
    # opts = options.Options(     listen_host=ip,    listen_port=8080 )
    opts = options.Options(listen_host="127.0.0.1", listen_port=8080)

    # m = DumpMaster(opts)
    m = DumpMaster(opts, with_termlog=False, with_dumper=False)
    task = asyncio.create_task(start(client, m))
    # try:
    #     # 用 sleep 控制寿命（跟你原逻辑一致）
    #     await asyncio.sleep(config.MINI_APP_TEST_TIME)
    # finally:
    #     # 按顺序收尾：先告诉上游不再发，再停 mitm，再取消任务
    #     with contextlib.suppress(Exception):
    #         client.close()
    #     with contextlib.suppress(Exception):
    #         m.shutdown()
    #     with contextlib.suppress(asyncio.CancelledError, Exception):
    #         task.cancel()
    #         await task
    # print("traffic monitor end")
    try:
        # 不再 sleep，这一句会一直挂着，直到：
        #  - 你在外部进程对本进程发 terminate / Ctrl+C
        #  - 或 m.shutdown() 被调用（目前只有 finally 里会调）
        await task
    except asyncio.CancelledError:
        # 外部 terminate 时会进这里，正常忽略
        pass
    finally:
        # 按顺序收尾：先告诉上游不再发，再停 mitm，再取消任务
        with contextlib.suppress(Exception):
            client.close()
        with contextlib.suppress(Exception):
            m.shutdown()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.cancel()
            await task
    print("traffic monitor end")


if __name__ == "__main__":
    client = traffic_transfer_client_pc.Client(config.TCP_PORT)
    try:
        asyncio.run(main(client))
    except (asyncio.CancelledError, RuntimeError):
        # 被外部 kill 时这里可能会抛 RuntimeError，简单忽略
        print("Cancel mitmproxy")
    print("traffic monitor end (process exit)")
    