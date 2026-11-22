# 信息收集系统 · 公网版（info-radar）

把本机「信息抓取」薄壳系统公网化：**GitHub Pages 静态前端 + 独立公网 Python 后端 + 持久化数据 + 所有者认证隔离**。
关闭本机服务后仍可使用；历史记录可恢复；访客仅见虚构示例，真实数据登录后访问。

## 功能
- 左栏：圆桌（Co-STORM 现场检索）/ 文章（STORM 多视角）/ 研究报告（GPT Researcher）/ 方案 / 任务卡 / 历史会话
- 右栏：翻译答疑（自动注入左栏上下文，服务端落盘，重载恢复，request_id 防重）
- 任务卡：生成→待执行→领取→回写，本机执行 Agent 经 HTTPS 同步（云端不写本机 Obsidian、无任意命令接口）

## 架构
```
frontend/   静态前端（index.html + history.js + auth.js + config.js），GitHub Pages 发布
backend/    FastAPI 薄壳（server.py）+ 历史存储（history_store.py）+ 持久化同步（cloud_store.py）
            + 虚构示例（demo_data.py）+ 引擎脚本（run_e1/run_article/run_e2_api）+ DeepSeek 插件
Dockerfile  双 venv（gptr py3.12 / storm py3.11+constraints）+ torch CPU + 构建期烘焙嵌入模型
entrypoint.sh  建持久目录→引擎软链→从平台 secrets 生成引擎 .env（绝不落持久盘/同步）→起服务
```
- 引擎与壳进程隔离，零 fork；模型与检索均走 DeepSeek（一个 key），嵌入用本地 all-MiniLM-L6-v2。
- 持久化：业务数据写 `/data`，启动从私有 HF dataset 恢复，写后同步 + 45s 周期兜底；`.env`/密钥不同步。
- 认证：所有者 JWT（HS256，Bearer 头，避免三方 Cookie 问题）；访客 GET 返回虚构示例，写操作 401。
- CORS：精确前端 origin，`allow_credentials=False`，禁通配。

## 安全红线
- 公开仓库与 Pages 产物不含密钥、个人历史、报告、教材、venv、模型缓存、日志。
- 前端不依赖环回地址/本机目录；一律走 `config.js` 的 `API_BASE`。
- 旧 45 条记录整体留 legacy 档，不按内容猜拆；导入只读，原件 SHA256 不变。
- 任务重启后未完成标记 interrupted，可查可重试；不伪造"已交接"。

## 部署
见 `docs/部署说明.md`（Plan A：HF PRO + Docker Space + 私有 dataset；Plan B：Oracle 永久免费 ARM + Tailscale Funnel）。
变量名模板见 `.env.example`（值绝不提交）。HF Space 元数据见 `hf-space-README.md`（推送到 Space 时作为 README.md）。

## 本地开发
```
uv venv --python 3.12 venv-dev
uv pip install -p venv-dev/bin/python -r backend/requirements-server.txt
# 配置 backend/.env（参考 .env.example，自填密钥）与 DATA_DIR
cd backend && ../venv-dev/bin/python -m uvicorn server:app --port 7860
```
后端验收测试见构建机 `test_backend.py`（39 项断言：认证/示例/迁移/防重/任务卡/CORS/重启恢复/限流）。
