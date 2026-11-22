# 交接与迭代 · 信息抓取系统（公网版）

> 给接手迭代的 Agent：先读本页 → 再读 `HANDOFF_2026-11-22_公网部署.md` → 最后看 `迭代日志.md`。

## 三句话现状
1. 我们部署了一个**公网可访问**的网站：**http://47.97.204.93/**
2. **前端是纯静态、可改**：在仓库 `frontend/`（`index.html / history.js / auth.js / config.js`）。
3. **访客只看到虚构示例；所有者登录后看到真实数据与历史。**

## 关键链接
| 项 | 位置 |
|---|---|
| 线上系统 | http://47.97.204.93/ |
| 代码仓库 | https://github.com/Vansinver/info-radar |
| 前端（可改） | `frontend/` |
| 部署经过 | `docs/交接与迭代/HANDOFF_2026-11-22_公网部署.md` |
| 迭代日志（每次必写） | `docs/交接与迭代/迭代日志.md` |

## 能不能改、怎么改
能。改 `frontend/*` → 提交仓库 → 由**服务器所有者**在服务器执行 `bash /opt/info-radar/redeploy.sh`（= `git fetch && git reset --hard origin/main && systemctl restart info-radar`）→ 刷新即生效。

约束：
- `frontend/config.js` 的 `window.API_BASE` 必须保持空串（同源）；**不得**改成 `127.0.0.1`/`localhost`/本机路径。
- 改后端 `backend/server.py` 同样需要重启服务。

## 强制规则（每次迭代必做）
每次迭代（无论谁做）必须在 `迭代日志.md` 追加一条：**版本号 / 日期 / 改了什么 / 验证证据 / 回滚方式 / 记录人**。
不写迭代日志 = 该次迭代视为未完成。

## 边界
- 本仓库只放代码与脱敏说明；**任何密钥/密码/聊天记录不进仓库**。
- `DEEPSEEK_API_KEY` 等凭证只写在服务器 `/etc/info-radar.env`，绝不进这里。
- 本地 `未来预期.md`（本地 Agent 迭代平台治理）属本地，不在本仓库。
