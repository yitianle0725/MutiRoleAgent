import requests

url = "https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/mcp"

try:
    resp = requests.get(url, timeout=10)
    print(f"✅ 网络正常，状态码：{resp.status_code}")
except Exception as e:
    print("❌ 网络不通，连接被阻断")
    print(e)