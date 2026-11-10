# 角色聊天 Demo

Streamlit + DeepSeek 的角色聊天，支持流式回复、角色卡/世界书上传、可查看的长期记忆。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEEPSEEK_API_KEY="sk-..."
streamlit run webapp/app.py
```

## Streamlit Cloud 部署

1. 连接 GitHub 仓库；
2. Main file path: `webapp/app.py`；
3. Python: 3.12；
4. Secrets:

```toml
DEEPSEEK_API_KEY = "sk-..."
APP_PASSWORD = "给组员的访问口令"
```

注意：当前是 Demo 版，聊天/记忆/上传存在容器本地，应用重启会清空。
