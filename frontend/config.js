// 部署时注入正式后端地址与版本 SHA；本地/同源运行时留空即可（相对路径）。
// 红线：前端任何路径不得依赖环回地址或本机目录；一律走 API_BASE 相对/绝对公网基址。
window.API_BASE = "";
window.BUILD_VERSION = "pages-interim";

/* ===== v0.2.6 / v0.2.7 前端补丁（只改本文件，不动 index.html、不动后端） =====
   v0.2.6 右栏「新对话」按钮
   v0.2.7 长提问折叠 / 一键到底箭头 / 输入框自动长高 / 去掉三个快捷问题
*/
(function () {
  var CSS = [
    /* 1) 去掉输入框上方的三个快捷问题 */
    '.chatbar > div:first-child{display:none!important}',
    /* 2) 长提问折叠 */
    '#msgs .msg.user .bubble.clamp-on{max-height:160px;overflow:hidden}',
    '#msgs .expand-btn{display:block;margin:4px 0 0 auto;background:none;border:0;color:#7a8a86;font-size:12px;cursor:pointer;padding:2px 4px}',
    '#msgs .expand-btn:hover{color:#0f766e;text-decoration:underline}',
    /* 3) 一键到底箭头（挂在输入条上方） */
    '.chatbar{position:relative}',
    '#toBottom{position:absolute;right:10px;top:-44px;width:34px;height:34px;border-radius:50%;border:1px solid #d8e3e0;background:#fff;color:#0f766e;font-size:16px;line-height:1;display:none;z-index:30;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.10)}',
    '#toBottom:hover{background:#f2f8f6}',
    /* 4) 输入框自适应高度 */
    '#chatInput{resize:none;overflow-y:auto;line-height:1.6}'
  ].join('\n');

  function injectCSS() {
    if (document.getElementById('ui-patch-css')) return;
    var s = document.createElement('style');
    s.id = 'ui-patch-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    injectCSS();

    var msgs = document.getElementById('msgs');
    var chatbar = document.querySelector('.chatbar');
    var ta = document.getElementById('chatInput');

    /* ---------- 1. 右栏「新对话」 ---------- */
    var bar = document.querySelector('.right .history-toolbar');
    var ref = document.getElementById('showHistory');
    if (bar && ref && !document.getElementById('newChatQuick')) {
      var nb = document.createElement('button');
      nb.id = 'newChatQuick';
      nb.className = 'btn ghost';
      nb.textContent = '新对话';
      nb.onclick = async function () {
        if (window.__guest) return toast('示例模式：登录后即可开启新对话');
        if (typeof H === 'undefined' || H.busy) return toast('请等当前回复完成');
        try {
          var d = new Date();
          var p = function (n) { return String(n).padStart(2, '0'); };
          var title = '新对话 ' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
          var item = await post('/api/history', { title: title });
          await chooseSession(item.id);
          if (msgs && !msgs.children.length) {
            msgs.innerHTML = '<div class="msg bot"><div class="who">翻译</div><div class="bubble">新对话已开始。旧记录都保留在「历史会话」里，随时可以切回去。</div></div>';
          }
          document.getElementById('chatInput').focus();
          toast('已开启新对话');
        } catch (e) { historyError(e); }
      };
      bar.insertBefore(nb, ref);
    }

    /* ---------- 2. 长提问折叠 ---------- */
    function clampBubbles() {
      if (!msgs) return;
      msgs.querySelectorAll('.msg.user .bubble').forEach(function (b) {
        if (b.dataset.clampReady) return;
        b.dataset.clampReady = '1';
        if (b.scrollHeight > 176) {
          b.classList.add('clamp-on');
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'expand-btn';
          btn.textContent = '展开全文';
          btn.onclick = function () {
            var on = b.classList.toggle('clamp-on');
            btn.textContent = on ? '展开全文' : '收起';
            if (!on) b.scrollIntoView({ block: 'nearest' });
          };
          b.insertAdjacentElement('afterend', btn);
        }
      });
    }

    /* ---------- 3. 一键到底 ---------- */
    var toBottom = null;
    function updateArrow() {
      if (!toBottom || !msgs) return;
      var gap = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight;
      toBottom.style.display = gap > 80 ? 'block' : 'none';
    }
    if (chatbar && msgs) {
      toBottom = document.createElement('button');
      toBottom.id = 'toBottom';
      toBottom.type = 'button';
      toBottom.title = '回到底部';
      toBottom.textContent = '↓';
      toBottom.onclick = function () { msgs.scrollTo({ top: msgs.scrollHeight, behavior: 'smooth' }); };
      chatbar.appendChild(toBottom);
      msgs.addEventListener('scroll', updateArrow, { passive: true });
    }

    /* ---------- 4. 输入框自动长高 ---------- */
    function grow() {
      if (!ta) return;
      ta.style.height = 'auto';
      var max = Math.round(window.innerHeight * 0.42);
      ta.style.height = Math.min(ta.scrollHeight, max) + 'px';
    }
    if (ta) {
      ta.addEventListener('input', grow);
      grow();
    }
    /* 发送后输入框会被清空，补一次复位 */
    if (typeof sendChat === 'function') {
      var _send = sendChat;
      sendChat = async function (txt) { await _send(txt); grow(); };
    }

    /* ---------- 消息变化后统一维护 ---------- */
    if (msgs && window.MutationObserver) {
      var timer = null;
      new MutationObserver(function () {
        clearTimeout(timer);
        timer = setTimeout(function () { clampBubbles(); updateArrow(); }, 60);
      }).observe(msgs, { childList: true, subtree: true });
    }
    clampBubbles();
    updateArrow();
  });
})();
