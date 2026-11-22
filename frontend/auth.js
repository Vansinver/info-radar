/* 公网版认证与连接状态。访客=虚构示例；所有者登录后进入真实工作区。 */
window.__guest = true;

function setConn(online, health) {
  const b = $('connBadge'); if (!b) return;
  if (!online) { b.textContent = '离线'; b.className = 'conn off'; return; }
  if (window.__guest) { b.textContent = '示例模式'; b.className = 'conn guest'; }
  else { b.textContent = '在线·已登录'; b.className = 'conn on'; }
}
function showLogin() { const o = $('loginOverlay'); if (o) { o.hidden = false; const u = $('loginUser'); if (u) u.focus(); } }
function hideLogin() { const o = $('loginOverlay'); if (o) o.hidden = true; }

async function authInit() {
  const t = authToken();
  if (t) {
    try {
      const r = await fetch((window.API_BASE || '') + '/api/me', { headers: { 'Authorization': 'Bearer ' + t } });
      window.__guest = !r.ok;
      if (!r.ok) localStorage.removeItem('radar_token');
    } catch (e) { window.__guest = true; }
  } else { window.__guest = true; }
  applyAuthUI();
}
function applyAuthUI() {
  const btn = $('authBtn'), banner = $('guestBanner');
  if (window.__guest) {
    if (btn) { btn.textContent = '登录'; btn.onclick = showLogin; }
    if (banner) banner.hidden = false;
  } else {
    if (btn) { btn.textContent = '退出'; btn.onclick = logout; }
    if (banner) banner.hidden = true;
  }
}
function logout() {
  localStorage.removeItem('radar_token'); window.__guest = true;
  applyAuthUI(); toast('已退出，回到示例模式'); location.reload();
}
async function doLogin() {
  const u = $('loginUser').value.trim(), p = $('loginPass').value;
  const err = $('loginError'); err.textContent = '';
  if (!u || !p) { err.textContent = '请输入用户名和密码'; return; }
  try {
    const r = await fetch((window.API_BASE || '') + '/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    });
    if (!r.ok) { let d; try { d = await r.json(); } catch (e) { d = {}; } err.textContent = d.detail || ('登录失败 HTTP ' + r.status); return; }
    const d = await r.json();
    localStorage.setItem('radar_token', d.token); window.__guest = false;
    hideLogin(); toast('登录成功，正在进入真实工作区'); location.reload();
  } catch (e) { err.textContent = '网络错误：' + e.message; }
}
async function authPoll() {
  try {
    const h = await api('/api/health'); setConn(true, h);
    const vb = $('verBadge'); if (vb) vb.textContent = 'v' + (h.version || window.BUILD_VERSION || 'dev');
  } catch (e) { setConn(false); }
}
window.showLogin = showLogin; window.setConn = setConn; window.authInit = authInit; window.authPoll = authPoll;
document.addEventListener('DOMContentLoaded', () => {
  const lb = $('loginBtn'); if (lb) lb.onclick = doLogin;
  const lc = $('loginCancel'); if (lc) lc.onclick = hideLogin;
  const lp = $('loginPass'); if (lp) lp.onkeydown = e => { if (e.key === 'Enter') doLogin(); };
});
