#!/usr/bin/env bash
# 信息收集系统 · Oracle Always Free ARM(aarch64) 机内部署脚本
# 前提：已通过 scp 把 app/ 与 private/ 放到 /opt/info-radar/{app,private}
# 以 root 或 sudo 运行：sudo bash setup.sh
# 幂等：可重复运行；不删除已有 /data 业务数据。
set -euo pipefail
ROOT=/opt/info-radar
DATA=/data
APP="$ROOT/app"
PRIV="$ROOT/private"
export DEBIAN_FRONTEND=noninteractive

echo "== 1. 系统依赖 =="
apt-get update -y
apt-get install -y curl git ca-certificates build-essential pkg-config libssl-dev rsync

echo "== 2. uv（管理 python 3.12/3.11 与 venv）=="
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi
export PATH="/usr/local/bin:$PATH"
uv python install 3.12 3.11

echo "== 3. 目录 =="
mkdir -p "$DATA"/{reports,discussions,solutions,taskcards,legacy,history,joblogs,articles_work}
mkdir -p "$ROOT/models" "$ROOT/hf-cache"

echo "== 4. E1 venv（gpt-researcher，py3.12，aarch64 CPU torch）=="
uv venv --python 3.12 "$ROOT/venv-gptr"
# aarch64 CPU torch 走默认 PyPI（download.pytorch.org/whl/cpu 无 aarch64）
uv pip install --python "$ROOT/venv-gptr/bin/python" torch --index-url https://pypi.org/simple
uv pip install --python "$ROOT/venv-gptr/bin/python" -r "$APP/backend/requirements-server.txt"
uv pip install --python "$ROOT/venv-gptr/bin/python" "gpt-researcher==0.17.0" langchain-huggingface sentence-transformers
uv pip install --python "$ROOT/venv-gptr/bin/python" -e "$APP/backend/gptr-deepseek-retriever"

echo "== 5. E2 venv（knowledge-storm，py3.11，constraints 锁版本）=="
uv venv --python 3.11 "$ROOT/venv-storm"
uv pip install --python "$ROOT/venv-storm/bin/python" torch --index-url https://pypi.org/simple
uv pip install --python "$ROOT/venv-storm/bin/python" -c "$APP/backend/constraints-storm.txt" "knowledge-storm==1.1.1" python-dotenv

echo "== 6. 烘焙嵌入模型 all-MiniLM-L6-v2（离线可用）=="
HF_HOME="$ROOT/hf-cache" "$ROOT/venv-gptr/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
p=snapshot_download("sentence-transformers/all-MiniLM-L6-v2", local_dir="/opt/info-radar/models/all-MiniLM-L6-v2")
print("model:",p)
PY

echo "== 7. 密钥与运行时环境（/etc/info-radar.env，root-only，绝不进 /data/仓库）=="
install -m 600 "$PRIV/.env" /etc/info-radar.env
cat >> /etc/info-radar.env <<EOF
DATA_DIR=$DATA
PY_GPTR=$ROOT/venv-gptr/bin/python
PY_STORM=$ROOT/venv-storm/bin/python
PORT=7860
PAGES_ORIGIN=https://vansinver.github.io
SPACE_ORIGIN=${SPACE_ORIGIN:-}
BUILD_SHA=${BUILD_SHA:-oracle-b}
HF_DATASET_REPO=
HF_TOKEN=
HF_HOME=$ROOT/hf-cache
EMBEDDING=huggingface:all-MiniLM-L6-v2
RETRIEVER=deepseek
FAST_LLM=deepseek:deepseek-flash
SMART_LLM=deepseek:deepseek-flash
HF_ENDPOINT=https://huggingface.co
EOF
chmod 600 /etc/info-radar.env

echo "== 8. 迁移业务数据（原件不动；legacy 整体导入）=="
cp -rn "$PRIV/reports/." "$DATA/reports/" 2>/dev/null || true
cp -rn "$PRIV/discussions/." "$DATA/discussions/" 2>/dev/null || true
# 方案 = 50_解决区 顶层 md（README/系统本体/教材页定位/调研方案/生图提示词），不含任务卡子目录
cp -n "$PRIV"/50_解决区/*.md "$DATA/solutions/" 2>/dev/null || true
cp -rn "$PRIV/50_解决区/任务卡/." "$DATA/taskcards/" 2>/dev/null || true
mkdir -p "$DATA/legacy"
cp -n "$PRIV/chat_history.jsonl" "$DATA/legacy/chat_history.jsonl" 2>/dev/null || true
# 兼容备选布局（若 private 已扁平化）
[ -d "$PRIV/solutions" ] && cp -rn "$PRIV/solutions/." "$DATA/solutions/" 2>/dev/null || true
[ -d "$PRIV/taskcards" ] && cp -rn "$PRIV/taskcards/." "$DATA/taskcards/" 2>/dev/null || true
echo "迁移计数：reports=$(ls "$DATA/reports"/*.md 2>/dev/null | wc -l) discussions=$(ls "$DATA/discussions"/* 2>/dev/null | wc -l) solutions=$(ls "$DATA/solutions"/*.md 2>/dev/null | wc -l) taskcards=$(ls "$DATA/taskcards"/TC-*.md 2>/dev/null | wc -l) legacy=$(wc -l < "$DATA/legacy/chat_history.jsonl" 2>/dev/null)"

echo "== 9. systemd 服务 =="
install -m 644 "$ROOT/deploy/oracle/info-radar.service" /etc/systemd/system/info-radar.service
systemctl daemon-reload
systemctl enable info-radar
systemctl restart info-radar
sleep 3
systemctl --no-pager status info-radar | head -12 || true

echo "== 10. 本机健康自检 =="
curl -fsS http://127.0.0.1:7860/api/health || echo "（服务尚在加载嵌入模型，稍后重试 curl）"

echo "== 11. Tailscale（安装；登录与 Funnel 由用户参与，见 RUNBOOK 阶段2）=="
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
echo "完成。下一步：tailscale up（用户登录）→ 启用 Funnel → tailscale funnel 7860"
