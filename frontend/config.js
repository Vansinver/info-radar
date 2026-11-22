// 部署时注入正式后端地址与版本 SHA；本地/同源运行时留空即可（相对路径）。
// 红线：前端任何路径不得依赖环回地址或本机目录；一律走 API_BASE 相对/绝对公网基址。
//  interim：后端未部署，API_BASE 留空 → 同源 /api 404 → 徽章显示“后端未接通”。
window.API_BASE = "";
window.BUILD_VERSION = "pages-interim";
