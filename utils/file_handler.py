import hashlib
import os
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from utils.logger_handler import logger
from langchain_core.documents import Document



def get_file_md5_hex(filepath: str):
    # 获取文件的md5的十六进制字符串
    if not os.path.exists(filepath):
        logger.error(f"[md5计算]文件{filepath}不存在")
        return

    if not os.path.isfile(filepath):
        logger.error(f"[md5计算]路径{filepath}不是文件")
        return

    md5_obj = hashlib.md5()
    chunk_size = 4096  # 4KB分片，避免文件过大爆内存
    try:
        with open(filepath, "rb") as f:  # 必须二进制读取
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)

        md5_hex = md5_obj.hexdigest()
        return md5_hex
    except Exception as e:
        logger.error(f"计算文件{filepath}md5失败，{str(e)}")
        return None

def listdir_with_allowed_type(path: str, allowed_types: tuple[str]):
    """返回文件夹内的文件列表（允许的文件后缀），递归扫描子目录。"""
    files = []

    if not os.path.isdir(path):
        logger.error(f"[listdir_with_allowed_type]{path}不是文件夹")
        return tuple(files)

    for root, _dirs, filenames in os.walk(path):
        for f in filenames:
            if f.endswith(allowed_types):
                files.append(os.path.join(root, f))

    return tuple(files)


def pdf_loader(filepath: str, passwd=None) -> list[Document]:
    return PyPDFLoader(filepath, passwd).load()


def txt_loader(filepath: str) -> list[Document]:
    return TextLoader(filepath, encoding="utf-8").load()


def json_loader(filepath: str) -> list[Document]:
    """加载 JSON 文件为 Document 列表。

    支持两种格式：
    1. Chara Card V2 角色卡 — 提取 description、first_mes、
       alternate_greetings、character_book entries、mes_example 等字段
    2. 通用 JSON — 拍平为 key: value 文本

    Args:
        filepath: JSON 文件绝对路径。

    Returns:
        Document 列表，含 page_content 与 metadata（source、file_type 等）。
    """
    import json
    documents: list[Document] = []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"[json_loader] JSON 解析失败: {filepath} — {e}")
        return []
    except Exception as e:
        logger.error(f"[json_loader] 文件读取失败: {filepath} — {e}")
        return []

    # —— 分支 1: Chara Card V2 角色卡 ——
    if isinstance(raw, dict) and raw.get("spec") == "chara_card_v2":
        data = raw.get("data", {})
        char_name = data.get("name", "Unknown")

        # description
        desc = data.get("description", "")
        if desc.strip():
            documents.append(Document(
                page_content=desc,
                metadata={"source": filepath, "file_type": "json",
                          "character": char_name, "section": "description"},
            ))

        # first_mes
        first = data.get("first_mes", "")
        if first.strip():
            documents.append(Document(
                page_content=first,
                metadata={"source": filepath, "file_type": "json",
                          "character": char_name, "section": "first_message"},
            ))

        # alternate_greetings
        for i, g in enumerate(data.get("alternate_greetings", [])):
            if isinstance(g, str) and g.strip():
                documents.append(Document(
                    page_content=g,
                    metadata={"source": filepath, "file_type": "json",
                              "character": char_name,
                              "section": f"alternate_greeting_{i + 1}"},
                ))

        # character_book entries
        for entry in data.get("character_book", {}).get("entries", []):
            if isinstance(entry, dict):
                name = entry.get("name", "unknown")
                content = entry.get("content", "")
                if content.strip():
                    documents.append(Document(
                        page_content=f"[{name}]\n{content}",
                        metadata={"source": filepath, "file_type": "json",
                                  "character": char_name, "section": "lorebook",
                                  "entry_name": name},
                    ))

        # mes_example
        example = data.get("mes_example", "")
        if example.strip():
            documents.append(Document(
                page_content=example,
                metadata={"source": filepath, "file_type": "json",
                          "character": char_name, "section": "example_messages"},
            ))

    # —— 分支 2: 通用 JSON → 拍平 ——
    else:
        def _flatten(obj, parent_key: str = "") -> list[tuple[str, str]]:
            pairs: list[tuple[str, str]] = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    new_key = f"{parent_key}.{k}" if parent_key else k
                    pairs.extend(_flatten(v, new_key))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    new_key = f"{parent_key}[{i}]"
                    pairs.extend(_flatten(item, new_key))
            else:
                text = str(obj).strip()
                if text:
                    pairs.append((parent_key, text))
            return pairs

        flat = _flatten(raw)
        if flat:
            content = "\n".join(f"{k}: {v}" for k, v in flat)
            documents.append(Document(
                page_content=content,
                metadata={"source": filepath, "file_type": "json",
                          "section": "flattened"},
            ))

    return documents