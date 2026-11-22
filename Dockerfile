FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/hf-cache \
    LITELLM_LOCAL_MODEL_COST_MAP=True

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# ---- E1 引擎 venv（Python 3.12）+ 壳服务依赖 ----
RUN uv venv --python 3.12 /app/backend/venv-gptr \
    && uv pip install --python /app/backend/venv-gptr/bin/python \
        torch --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --python /app/backend/venv-gptr/bin/python \
        -r /app/backend/requirements-server.txt \
        gpt-researcher==0.17.0 langchain-huggingface sentence-transformers \
    && uv pip install --python /app/backend/venv-gptr/bin/python \
        -e /app/backend/gptr-deepseek-retriever

# ---- E2 引擎 venv（Python 3.11，锁依赖） ----
RUN uv venv --python 3.11 /app/backend/venv-storm \
    && uv pip install --python /app/backend/venv-storm/bin/python \
        torch --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --python /app/backend/venv-storm/bin/python \
        -c /app/backend/constraints-storm.txt \
        knowledge-storm==1.1.1 python-dotenv

# ---- 构建期烘焙嵌入模型（运行期不再外网下载） ----
RUN /app/backend/venv-storm/bin/python -c \
        "from huggingface_hub import snapshot_download; snapshot_download('sentence-transformers/all-MiniLM-L6-v2', local_dir='/app/backend/models/all-MiniLM-L6-v2')" \
    && /app/backend/venv-gptr/bin/python -c \
        "from huggingface_hub import snapshot_download; snapshot_download('sentence-transformers/all-MiniLM-L6-v2')"

EXPOSE 7860
CMD ["/app/entrypoint.sh"]
