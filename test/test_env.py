from dotenv import load_dotenv
import os


# 加载环境变量
load_dotenv()

key = os.getenv("DASHSCOPE_API_KEY")

if key:
    print("✅ 成功读取到API密钥：", key[:20] + "******")
else:
    print("❌ 读取失败，检查.env文件名、位置、格式")