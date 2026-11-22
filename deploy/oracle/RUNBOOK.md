# Plan B 部署运行手册 · Oracle Always Free ARM + Tailscale Funnel（¥0）

> 用户已拍板：只用 Oracle 免费；开不出免费 ARM 就暂停如实报告，不擅自转付费。
> 红线：密钥/所有者凭证不进聊天/仓库/Pages；公开≠公开个人数据；不推整个 Obsidian 仓库；
> 原件不动；跨网络/手机终验由用户做；push≠发布成功。

## 架构
- 前端：GitHub Pages `https://vansinver.github.io/info-radar/`（静态，config.js 注入 API_BASE）。
- 后端：Oracle A1 ARM 实例（4 OCPU/24GB，aarch64，Ubuntu），systemd 跑 uvicorn 仅监听 127.0.0.1:7860。
- 公网入口：Tailscale Funnel → `https://<node>.<tailnet>.ts.net`（免费 HTTPS，无需开放 Oracle 入站端口）。
- 持久化：Oracle 启动卷（常驻，不随会话回收）；cloud_store 无 HF_TOKEN → local-disk 模式。
- 离站备份：/data → GitHub 私有仓库（PAT，systemd timer 周期 push）。
- 管理通道：VM 构建机经 SSH/scp（出站 22 已实测可达）→ 实例公网 IP:22。

## 部署专用 SSH 公钥（粘贴到 Oracle 实例 SSH keys；私钥留 VM，绝不外传）
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGBAbQUrd1xhr0qdwIP16w1xrf8NkLY7jNZhqj1N0/vB info-radar-deploy
```

## 阶段 1 · Oracle 账号 + ARM 实例（用户参与，风险闸门）
1. 注册/登录 https://cloud.oracle.com （需邮箱+手机验证；绑现有工行 Visa/万事达卡做身份验证，**不扣费**）。
   - Home Region 永久不可改：建议 ap-seoul-1 / ap-tokyo-1 / ap-singapore-1（离华近）；A1 容量紧张时可试 us-ashburn-1。
2. 创建实例：Compute → Instances → Create。
   - Image：Ubuntu 22.04 或 24.04（aarch64）。
   - Shape：Ampere → VM.Standard.A1.Flex，**4 OCPU / 24 GB**（Always Free 上限，单实例用满）。
   - Networking：新建/选公共子网 VCN，**分配公网 IPv4**。
   - SSH keys：粘贴上方公钥。
   - Boot volume：默认 50GB（免费块存储共 200GB）。
3. 安全列表 Ingress：放行 TCP 22（源可先 0.0.0.0/0，部署后收紧到 VM 出口 IP）。**无需放行 7860**（Funnel 隧道）。
4. 若提示 "Out of host capacity"：换可用性域/换时段重试；多次失败 → **暂停如实报告**（用户约定）。
5. 回报：实例公网 IP + 确认已加公钥 + 默认用户名（Ubuntu 镜像为 `ubuntu`）。

## 阶段 2 · 机内部署（我驱动 SSH）+ Tailscale（用户登录一次）
1. VM 打包传输：`tar czf bundle.tgz -C info-radar app deploy private` → scp 到实例 `/opt/info-radar/`。
   （private 含 .env+45条+reports/discussions/50_解决区；仅经 SSH 私有通道，不进仓库）
2. SSH 解包到 /opt/info-radar/{app,deploy,private}；`sudo bash /opt/info-radar/deploy/oracle/setup.sh`。
   - setup.sh：uv 装 py3.12/3.11 → 双 venv（aarch64 CPU torch 走默认 PyPI）→ 烘焙嵌入模型 →
     /etc/info-radar.env（600）→ 迁移 /data → systemd 起服务 → 装 tailscaled。
3. 自检：`curl http://127.0.0.1:7860/api/health` 返回 ok（key_present/persistence=local-disk）。
4. Tailscale（用户参与）：`sudo tailscale up` → 浏览器登录（GitHub/Google 等）→ 批准节点。
   - 在 tailnet 管理台启用 HTTPS Certificates 与 Funnel（免费个人版可用）。
   - `sudo tailscale funnel 7860` → 得 `https://<node>.<tailnet>.ts.net`。
   - 把该 URL 写入 /etc/info-radar.env 的 SPACE_ORIGIN，重启服务（CORS 精确 origin）。
5. 持久化：tailscaled + info-radar 均 systemd 开机自启；实例常驻，关用户电脑不影响。

## 阶段 3 · 离站备份（用户创建 PAT 一次）
1. 用户建 GitHub **私有**仓库 `vansinver/info-radar-data`（空仓）。
2. 用户建 fine-grained PAT：仅该仓库 Contents: Read/Write。把 PAT 经私有通道给我（或用户自填实例 /etc/info-radar-backup.env）。
3. 实例：写 /etc/info-radar-backup.env（600，BACKUP_REPO/BACKUP_PAT）→ 装 backup.service+backup.timer（每 10 分钟）→ 启用。
4. 验证：手动跑 backup.sh → 私有仓出现 data/ 副本；恢复演练=从私有仓拉回 /data 重启。

## 阶段 4 · 前端发布 + 验收
1. 注入 frontend/config.js：API_BASE=`https://<node>.<tailnet>.ts.net`，BUILD_VERSION=commit SHA。
2. 推 .github/workflows/pages.yml + config.js → 等 Pages deployment **成功** → 才报最终前端 URL。
3. 真实引擎端到端：跑一次低成本 E1（约 0.1–0.2 元）验证检索+成文+落盘+备份。
4. 逐项验收（见 docs/部署说明.md §5）：本机关 8600 后公网可用 / 45条+SHA恢复 / 访客仅示例 /
   仓库无密钥 / CORS / 重启 interrupted / 任务卡领取回写 / 引擎产出 / Pages 成功 / 手机跨网络**待用户终验**。
5. 回执写 `_系统迭代/`；未来预期仅有证据才勾选，不写"用户验收通过"；自审给通过/附条件通过/不通过。

## 休眠/上限交代
- Oracle Always Free ARM：常驻不休眠（实例不手动 stop 即一直跑）；4 OCPU/24GB/200GB 块存储免费额度内。
- 免费账号风险：Oracle 可能因闲置回收 Always Free 实例（需保持活动）；A1 容量短缺；home region 不可改。
- 并发：单实例；圆桌单会话；限流 jobs 5/h、chat 30/min、login 5/min。
- 持久化窗口：写后即时落 Oracle 盘 + 10 分钟离站备份；极端崩溃最多丢最近 10 分钟未备份写入。
