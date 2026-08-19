"""MutiRoleAgent 后端 API 层。

供 Web 前端与 CLI 复用的 FastAPI 服务；业务内核全部来自 ``agent`` / ``rag`` /
``memory`` / ``tools``，本包只做「输入来源」（HTTP/WS）与「输出呈现」的胶水。
"""
