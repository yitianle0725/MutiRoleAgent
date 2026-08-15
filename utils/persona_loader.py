"""
角色人设加载器
==============
从 ``prompts/roles/{slug}/soul/*.md`` 加载角色灵魂（V2 分层架构）。

旧版 V1（Chara Card JSON，``prompts/character_*.json``）已移除——
角色内容全部由 roles/ 分层包（_shared 底座 + soul + styles + worldbook）提供。

设计原则
--------
- **薄封装**：实际加载逻辑由 ``prompts.composer._load_soul()`` 完成，
  本模块只负责 none 处理与可用角色名查询。
- **与中间件协作**：中间件的 ``dynamic_prompt`` 钩子从
  ``runtime.context["persona"]`` 读取当前角色名，
  调用本模块的 ``load_persona_overlay()`` 拼合角色灵魂文本。
"""

from __future__ import annotations

from utils.logger_handler import logger

# 配置加载
def _load_persona_cfg() -> dict:
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/persona.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except Exception:
        return {}

_CHAR_CFG = _load_persona_cfg().get("characters", {})


# ==================== 角色名管理器 ====================

class PersonaLoader:
    """角色名管理器，提供可用角色列表（内容加载由 composer 完成）。

    使用方式::

        from utils.persona_loader import persona_loader
        names = persona_loader.available_names  # 所有可用角色名
    """

    @property
    def available_names(self) -> list[str]:
        """返回所有可用角色名（来自 config/persona.yaml 的 characters）。"""
        return list(_CHAR_CFG.keys())


# ==================== 模块级单例 ====================

# 全局唯一实例，供 app.py 等直接引用
persona_loader = PersonaLoader()


# ==================== 便捷函数（供 prompt_loader / middleware 调用） ====================

def load_persona_overlay(persona_name: str) -> str:
    """获取角色灵魂文本（共享底座 + base + soul）。

    如果 persona_name 为 None / 空字符串 / "none"，返回空字符串。
    """
    if not persona_name or persona_name.lower() == "none":
        return ""

    from prompts.composer import _load_soul

    soul = _load_soul(persona_name)
    if soul:
        logger.info(f"[PersonaLoader] 从 roles/{persona_name} 加载角色灵魂")
    else:
        logger.warning(f"[PersonaLoader] 未知角色或灵魂文件缺失: {persona_name}")
    return soul
