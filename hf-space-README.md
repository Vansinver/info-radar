---
title: Info Radar Backend
emoji: 📡
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# 信息收集系统 · 公网后端

FastAPI 薄壳公网版：文章/研究（GPT Researcher）、圆桌（Co-STORM）、报告、方案、
任务卡、翻译答疑、历史会话。前端在 GitHub Pages，本 Space 仅提供 API（也自带同源 UI 便于直连调试）。

## 运行时 secrets（在 Space Settings → Variables and secrets 配置，绝不进仓库）
- `DEEPSEEK_API_KEY`：模型与检索密钥
- `OWNER_USERNAME` / `OWNER_PASSWORD`：所有者登录凭证
- `JWT_SECRET`：登录令牌签名密钥
- `HF_TOKEN` / `HF_DATASET_REPO`：私有 dataset 持久化（如 `vansinver/info-radar-data`）
- `PAGES_ORIGIN`：前端精确 origin（如 `https://vansinver.github.io`）
- `BUILD_SHA`：前端版本标记

## 持久化
业务数据写入 `/data`，启动从私有 dataset 恢复，写后同步 + 45s 周期兜底。
`.env` 与任何密钥不同步。免费 cpu-basic 48h 不活动休眠，访客访问自动唤醒（冷启动约 1–2 分钟）。

## 安全
访客仅见虚构示例；真实数据须所有者登录（Bearer JWT）。CORS 精确 origin、不带凭证通配。
无任意命令执行接口；任务卡经领取/回写接口与本机执行 Agent 同步。
