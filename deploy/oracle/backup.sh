#!/usr/bin/env bash
# /data 业务数据 → GitHub 私有仓库 离站备份（Oracle 持久盘之外的第二副本）
# 由 systemd timer 周期触发；PAT 经 /etc/info-radar-backup.env（root-only）注入，绝不进仓库/聊天。
set -euo pipefail
source /etc/info-radar-backup.env   # BACKUP_REPO=owner/repo  BACKUP_PAT=github_pat_xxx
DATA=/data
WORK=/opt/info-radar/backup
mkdir -p "$WORK"; cd "$WORK"
if [ ! -d .git ]; then
  git init -q
  git remote add origin "https://x-access-token:${BACKUP_PAT}@github.com/${BACKUP_REPO}.git"
  git config user.email "backup@info-radar.local"; git config user.name "info-radar-backup"
fi
git remote set-url origin "https://x-access-token:${BACKUP_PAT}@github.com/${BACKUP_REPO}.git"
# 同步 /data（排除引擎 .env 等密钥；/data 本就不含 .env）
rsync -a --delete --exclude '.env' --exclude '*.pyc' --exclude '__pycache__' "$DATA/" "$WORK/data/"
git add -A
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git commit -qm "backup $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git branch -M main
git push -q origin main
echo "pushed $(date -u +%H:%M:%S)"
