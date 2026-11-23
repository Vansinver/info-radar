// 部署时注入正式后端地址与版本 SHA；本地/同源运行时留空即可（相对路径）。
// 红线：前端任何路径不得依赖环回地址或本机目录；一律走 API_BASE 相对/绝对公网基址。
//  interim：后端未部署，API_BASE 留空 → 同源 /api 404 → 徽章显示“后端未接通”。
window.API_BASE = "";
window.BUILD_VERSION = "pages-interim";

/* v0.2.6 右栏「新对话」入口：不动 index.html，DOM 就绪后插到「历史会话」左边。
   逻辑复用 history.js 的 post / chooseSession / toast / historyError 与 H 状态。 */
(function () {
  function addBtn() {
    var bar = document.querySelector('.right .history-toolbar');
    var ref = document.getElementById('showHistory');
    if (!bar || !ref || document.getElementById('newChatQuick')) return;
    var b = document.createElement('button');
    b.id = 'newChatQuick';
    b.className = 'btn ghost';
    b.textContent = '新对话';
    b.onclick = async function () {
      if (window.__guest) return toast('示例模式：登录后即可开启新对话');
      if (typeof H === 'undefined' || H.busy) return toast('请等当前回复完成');
      try {
        var d = new Date();
        var p = function (n) { return String(n).padStart(2, '0'); };
        var title = '新对话 ' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
        var item = await post('/api/history', { title: title });
        await chooseSession(item.id);
        var msgs = document.getElementById('msgs');
        if (msgs && !msgs.children.length) {
          msgs.innerHTML = '<div class="msg bot"><div class="who">翻译</div><div class="bubble">新对话已开始。旧记录都保留在「历史会话」里，随时可以切回去。</div></div>';
        }
        document.getElementById('chatInput').focus();
        toast('已开启新对话');
      } catch (e) { historyError(e); }
    };
    bar.insertBefore(b, ref);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addBtn);
  else addBtn();
})();
