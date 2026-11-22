#!/usr/bin/env bash
# 容器启动：建持久目录 → 引擎工作目录软链 → 从平台 secrets 生成引擎 .env（绝不落持久盘/同步）→ 起服务
set -e
DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/reports" "$DATA_DIR/discussions" "$DATA_DIR/solutions" \
         "$DATA_DIR/taskcards" "$DATA_DIR/history" "$DATA_DIR/legacy" \
         "$DATA_DIR/joblogs" "$DATA_DIR/articles_work"
cd /app/backend

# 引擎脚本以 HERE 相对路径写 reports/discussions/articles_work → 软链到持久盘
for d in reports discussions articles_work; do
  if [ ! -e "$d" ]; then ln -s "$DATA_DIR/$d" "$d"; fi
done

# 引擎 .env：仅来自平台运行时 secrets，容器内临时文件，不进 dataset、不进仓库
cat > /app/backend/.env <<EOF
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
RETRIEVER=${RETRIEVER:-deepseek}
FAST_LLM=${FAST_LLM:-deepseek:deepseek-flash}
SMART_LLM=${SMART_LLM:-deepseek:deepseek-flash}
EMBEDDING=${EMBEDDING:-huggingface:all-MiniLM-L6-v2}
HF_ENDPOINT=${HF_ENDPOINT:-https://huggingface.co}
EOF

exec /app/backend/venv-gptr/bin/python -m uvicorn server:app \
     --host 0.0.0.0 --port "${PORT:-7860}" --log-level warning
