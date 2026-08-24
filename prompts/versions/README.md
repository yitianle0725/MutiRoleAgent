# Prompt 版本

每个 Prompt 使用独立目录和版本文件，例如 `roleplay/v1.txt` 与 `roleplay/v1.json`。
发布前先运行离线评测，再把版本号写入 `PROMPT_*_VERSION`，不要直接依赖未审核的 `latest`。
