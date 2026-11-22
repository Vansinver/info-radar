/* 公网认证 UI：登录浮层 + 连接状态徽章 + 访客横幅。token 存 localStorage，api() 自动附 Bearer。 */
const AUTH_KEY='radar_token';
function getToken(){ return localStorage.getItem(AUTH_KEY)||''; }
function setToken(t){ if(t) localStorage.setItem(AUTH_KEY,t); else localStorage.removeItem(AUTH_KEY); }
function isOwner(){ return !window.__guest; }

function showLogin(){ $('loginOverlay').hidden=false; $('loginUser').focus(); }
function hideLogin(){ $('loginOverlay').hidden=true; $('loginError').textContent=''; $('loginPass').value=''; }

function setConn(online, health){
  const b=$('connBadge');
  if(!online){ b.textContent='离线'; b.className='conn off'; return; }
  if(health && health.owner){ b.textContent='在线 · 已登录'; b.className='conn on'; }
  else { b.textContent='示例模式'; b.className='conn guest'; }
}

async function authInit(){
  // 用原始 fetch 探测（避免 api() 的 401 自动弹登录）
  try{
    const t=getToken();
    const r=await fetch((window.API_BASE||'')+'/api/me',{headers:t?{'Authorization':'Bearer '+t}:{}});
    if(r.ok){ window.__guest=false; $('authBtn').textContent='退出'; $('guestBanner').hidden=true; }
    else { window.__guest=true; $('authBtn').textContent='登录'; $('guestBanner').hidden=false; }
  }catch(e){ window.__guest=true; }
}

async function authPoll(){
  try{
    const h=await api('/api/health');
    setConn(true,h);
    if($('verBadge')) $('verBadge').textContent='v'+(h.version||window.BUILD_VERSION||'dev');
    if(h.owner){ window.__guest=false; $('guestBanner').hidden=true; $('authBtn').textContent='退出'; }
    else { window.__guest=true; $('guestBanner').hidden=false; $('authBtn').textContent='登录'; }
  }catch(e){ setConn(false); }
}

$('authBtn').onclick=async()=>{
  if(isOwner()){ setToken(''); window.__guest=true; location.reload(); return; }
  showLogin();
};
$('loginCancel').onclick=hideLogin;
$('loginBtn').onclick=async()=>{
  const u=$('loginUser').value.trim(), p=$('loginPass').value;
  if(!u||!p){ $('loginError').textContent='请输入用户名和密码'; return; }
  $('loginBtn').disabled=true;
  try{
    const r=await fetch((window.API_BASE||'')+'/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    if(!r.ok){ const d=await r.json().catch(()=>({})); $('loginError').textContent=d.detail||('登录失败 HTTP '+r.status); return; }
    const d=await r.json(); setToken(d.token); window.__guest=false; hideLogin(); location.reload();
  }catch(e){ $('loginError').textContent='网络错误：'+e.message; }
  finally{ $('loginBtn').disabled=false; }
};
$('loginPass').onkeydown=e=>{ if(e.key==='Enter') $('loginBtn').click(); };
window.showLogin=showLogin;
window.setConn=setConn;
window.authInit=authInit;
window.authPoll=authPoll;
