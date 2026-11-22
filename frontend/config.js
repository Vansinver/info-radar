// 公网部署配置：后端 API 基址（HF Space 或 Tailscale Funnel 的 HTTPS 域名）。
// 部署时由部署脚本注入真实后端地址；同源部署（Space 直挂前端）时留空字符串即可。
// 严禁指向 127.0.0.1 / localhost / 本机目录。
window.API_BASE = "";
window.BUILD_VERSION = "pages-placeholder";
