"""
layout_novel.py
清洗同目录下的小说 TXT 文件：
1. 统一换行符（\r\n → \n）
2. 合并多余空行（段间只保留一个空行）
3. 去除首尾多余空白
"""
import os
import re
import glob

def clean_text(text: str) -> str:
    """清洗文本：统一换行、合并多余空行"""
    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # 合并 3 个及以上连续换行为 2 个（段间一个空行）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除首尾空白
    text = text.strip()
    # 确保文件以换行结尾
    text += '\n'
    return text

def process_file(filepath: str):
    """处理单个 TXT 文件"""
    # 用 GBK 编码文件名以正确显示中文
    fname = os.path.basename(filepath)
    print(f"[处理] {fname}")

    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()

    cleaned = clean_text(original)

    # 统计
    orig_lines = original.count('\n')
    clean_lines = cleaned.count('\n')
    orig_size = len(original.encode('utf-8'))
    clean_size = len(cleaned.encode('utf-8'))

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(cleaned)

    print(f"  [OK] 行数: {orig_lines} -> {clean_lines}, 大小: {orig_size/1024:.1f}KB -> {clean_size/1024:.1f}KB")

if __name__ == "__main__":
    # 批量处理同目录下所有 TXT（取消注释即可启用）
    # script_dir = os.path.dirname(os.path.abspath(__file__))
    # txt_files = glob.glob(os.path.join(script_dir, "*.txt"))
    #
    # if not txt_files:
    #     print("[ERROR] 当前目录没有找到 .txt 文件")
    # else:
    #     print(f"找到 {len(txt_files)} 个 TXT 文件\n")
    #     for fp in txt_files:
    #         process_file(fp)
    #     print(f"\n[DONE] 全部处理完成")

    # 输入单个文件路径进行清洗
    file_path = input("请输入小说文件路径（拖拽文件到终端即可）：").strip().strip('"')
    if not file_path:
        print("[ERROR] 未输入文件路径")
    elif not os.path.exists(file_path):
        print(f"[ERROR] 文件不存在: {file_path}")
    else:
        process_file(file_path)
