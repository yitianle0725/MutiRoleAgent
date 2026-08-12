"""
yaml
k: v
冒号后面要有空格
"""
import yaml
from utils.path_tool import get_abs_path


def load_rag_config(config_path: str = get_abs_path("config/rag.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_chroma_config(config_path: str = get_abs_path("config/chroma.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_prompts_config(config_path: str = get_abs_path("config/prompts.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_agent_config(config_path: str = get_abs_path("config/agent.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)

def load_gate_config(config_path: str = get_abs_path("config/gate.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_keywords_config(config_path: str = get_abs_path("config/keywords.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_decision_config(config_path: str = get_abs_path("config/decision.yaml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


rag_config = load_rag_config()
chroma_config = load_chroma_config()
prompts_config = load_prompts_config()
agent_config = load_agent_config()
gate_config = load_gate_config()
keywords_config = load_keywords_config()
decision_config = load_decision_config()

if __name__ == "__main__":
    print(rag_config["chat_model_name"])
    # print(chroma_config)
    # print(prompts_config)
    # print(agent_config)