/* 历史会话 UI（公网版）：复用 index.html 的 S/api/post/esc/currentContext/updateCtx。
   增量：导出走鉴权 blob；访客守卫（不写云端）；示例会话只读。原有右栏/左栏/资料联动逻辑保留。 */
S.history={active:null,items:[],detail:null,context:null};
S.chatSending=false; S.chatPending=null;

async function historyAuthBlob(path, filename, download){
  const t=localStorage.getItem('radar_token')||'';
  const r=await fetch((window.API_BASE||'')+path,{headers:t?{'Authorization':'Bearer '+t}:{}});
  if(!r.ok){ toast('导出失败 HTTP '+r.status); return; }
  const blob=await r.blob(); const u=URL.createObjectURL(blob);
  if(download){ const a=document.createElement('a'); a.href=u; a.download=filename; a.click(); }
  else window.open(u,'_blank');
  setTimeout(()=>URL.revokeObjectURL(u),60000);
}
function bindExport(id, fmt){
  const el=$(id);
  el.onclick=async(e)=>{ e.preventDefault(); if(!S.history.active){toast('先选择会话');return;} await historyAuthBlob('/api/history/'+encodeURIComponent(S.history.active)+'/export?format='+fmt, 'session-'+S.history.active+'.'+fmt, true); };
  el.href='#';
}
function renderHistoryList(items){
  const list=$('sessionList');
  list.innerHTML=items.map(x=>`<button class="session-item${x.id===S.history.active?' selected':''}" data-id="${esc(x.id)}"><strong>${esc(x.title)}</strong><small>${x.message_count} 条问答 · ${esc(x.updated_at||'')}</small></button>`).join('') || '<p class="sub">没有找到会话。可新建讨论；旧版记录不会猜测拆分。</p>';
  list.querySelectorAll('button').forEach(b=>b.onclick=()=>openHistorySession(b.dataset.id));
}
async function loadHistoryList(){
  const q=$('historySearch').value.trim();
  try{ const result=await api('/api/history'+(q?'?q='+encodeURIComponent(q):'')); S.history.items=result.sessions; renderHistoryList(result.sessions); }
  catch(e){ $('sessionList').innerHTML='<p class="sub">历史列表读取失败：'+esc(e.message)+'</p>'; }
}
function setHistoryStatus(message,error){$('historyStatus').textContent=message;$('historyStatus').style.color=error?'var(--danger)':'var(--sub)';}
function historyError(e){setHistoryStatus('历史连接失败：'+e.message,true);$('historyRetry').hidden=false;}
function renderHistoryMessages(messages,query){
  const q=(query||'').trim().toLowerCase(), filtered=q?messages.filter(m=>(m.content||'').toLowerCase().includes(q)):messages;
  $('historyMessageCount').textContent=q?`找到 ${filtered.length} 条 / 共 ${messages.length} 条`:`共 ${messages.length} 条消息`;
  $('historyMessages').innerHTML=filtered.map(m=>`<div class="msg ${esc(m.role)}"><div class="who">${m.role==='user'?'我':m.role==='note'?'交接':'翻译'} · ${esc(m.ts||'')}</div><div class="bubble">${m.role==='assistant'?(m.html||esc(m.content)):esc(m.content)}</div></div>`).join('') || '<p class="sub">没有匹配消息。</p>';
}
function renderRelated(related){
  const el=$('relatedFiles');
  el.innerHTML=related.map(x=>`<button class="related-file" data-kind="${esc(x.kind)}" data-name="${esc(x.name)}">[${esc(x.kind)}] ${esc(x.name)}</button>`).join('') || '<p class="sub">此会话尚未关联报告、圆桌、方案或任务卡。</p>';
  el.querySelectorAll('button').forEach(b=>b.onclick=()=>openHistoryAsset(b.dataset.kind,b.dataset.name));
}
function showHistoryTab(){$('showHistory').click();}
async function openHistoryAsset(kind,name){
  try{
    if(kind==='report'){await openReport(name);showHistoryTab();}
    else if(kind==='solution'){await openSolution(name);showHistoryTab();}
    else if(kind==='taskcard'){await openCard(name);showHistoryTab();}
    else {const result=await api('/api/discussions/'+encodeURIComponent(name));$('historyDocumentTitle').textContent=name;$('historyDocument').innerHTML=result.html||`<pre>${esc(result.raw||'')}</pre>`;$('historyDocumentPanel').hidden=false;}
    await recordVisit(kind,name);
  }catch(e){toast('资料打开失败：'+e.message);}
}
async function recordVisit(kind,name){
  if(!S.history.active || window.__guest) return;
  try{ S.history.context=await post('/api/history/'+encodeURIComponent(S.history.active)+'/visit',{kind,name}); updateCtx(); }
  catch(e){toast('关联记录失败：'+e.message);}
}
async function openHistorySession(id,refreshMessages){
  try{
    const result=await api('/api/history/'+encodeURIComponent(id));
    S.history.active=id;S.history.detail=result;S.history.context=result.context;
    $('historyTitle').textContent=result.session.title;$('activeSession').textContent='当前：'+result.session.title;
    $('historyMeta').textContent=`创建 ${result.session.created_at} · 更新 ${result.session.updated_at}`;
    renderHistoryMessages(result.messages,$('messageSearch').value);renderRelated(result.related);
    $('browseEvents').textContent=result.browse_events.map(x=>`${x.ts} · ${x.kind} · ${x.name}`).join('\n') || '暂无浏览记录。';
    if(refreshMessages!==false){renderHistory(result.messages);}
    bindExport('exportMd','md');bindExport('exportJson','json');renderHistoryList(S.history.items);
    $('historyRetry').hidden=true;setHistoryStatus('已加载会话；右栏可以继续聊天。',false);updateCtx();
  }catch(e){historyError(e);}
}
async function createHistorySession(title){
  try{ const result=await post('/api/history',{title:title||'新讨论'}); await loadHistoryList(); await openHistorySession(result.id); $('newSessionTitle').value='';toast('新讨论已创建，旧讨论保持原样。'); }catch(e){toast(e.message);}
}
function defaultSession(){ if(window.__guest) return 'demo-session'; return S.history.items.some(x=>x.id==='legacy')?'legacy':S.history.items[0]?.id; }
async function historyBoot(){
  await loadHistoryList();const id=defaultSession();if(id) await openHistorySession(id);else setHistoryStatus('还没有会话，请新建讨论。',false);
}
async function loadHistoryAssets(){
  const groups=[['报告',await api('/api/reports')],['圆桌',await api('/api/discussions')],['方案',await api('/api/solutions')],['任务卡',await api('/api/taskcards')]];
  $('historyAsset').innerHTML=groups.flatMap(([label,items])=>items.map(x=>`<option value="${esc(label==='报告'?'report':label==='圆桌'?'discussion':label==='方案'?'solution':'taskcard')}|${esc(x.name)}">[${label}] ${esc(x.name)}</option>`)).join('');
}
$('historyAssetOpen').onclick=()=>{const [kind,name]=$('historyAsset').value.split('|');if(kind&&name)openHistoryAsset(kind,name);};
$('historyCloseDocument').onclick=()=>{$('historyDocumentPanel').hidden=true;};
$('historyRefresh').onclick=()=>S.history.active?openHistorySession(S.history.active):loadHistoryList();
$('historyRetry').onclick=historyBoot;
$('newHistorySession').onclick=()=>createHistorySession($('newSessionTitle').value.trim());
$('historySearch').oninput=()=>loadHistoryList();
$('messageSearch').oninput=()=>{if(S.history.detail)renderHistoryMessages(S.history.detail.messages,$('messageSearch').value);};
$('showHistory').onclick=()=>{document.querySelector('.tabs button[data-tab="history"]').click();loadHistoryAssets().catch(()=>{});};

/* 会话感知上下文：当前资料 + 当前会话消息，避免新讨论自动读取旧讨论。 */
const historyBaseContext=currentContext;
currentContext=function(){
  const base=historyBaseContext();
  if(S.history.context) return {label:S.history.context.label,text:S.history.context.text};
  if(base.text) return base;
  if(S.history.detail){const messages=S.history.detail.messages.slice(-8).map(m=>`[${m.role}] ${m.content}`).join('\n\n');return {label:'会话 '+S.history.detail.session.title,text:messages};}
  return {label:'',text:''};
};

/* 统一发送队列：每次只发一条，失败保留输入，成功后以服务端记录为准。 */
async function sendChat(text){
  text=(text||'').trim();if(!text)return;
  if(window.__guest){toast('示例模式只读，登录后即可提问');if(window.showLogin)window.showLogin();return;}
  if(!S.history.active){toast('请先选择或新建会话');return;}
  if(S.chatSending){S.chatPending=text;toast('当前回答生成中，下一条已排队');return;}
  const sessionId=S.history.active, requestId=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());
  S.chatSending=true;$('chatSend').disabled=true;$('chatInput').value='';addMsg('user',text);
  const thinking=document.createElement('div');thinking.className='msg bot';thinking.innerHTML='<div class="who">翻译</div><div class="bubble">…</div>';$('msgs').appendChild(thinking);
  const c=currentContext();
  try{
    await post('/api/chat',{message:text,session_id:sessionId,request_id:requestId,context:c.text,context_label:c.label});
    thinking.remove();
    if(S.history.active===sessionId){await openHistorySession(sessionId);}
    else {const saved=await api('/api/history/'+encodeURIComponent(sessionId));renderHistory(saved.messages);}
    setHistoryStatus('回答已保存。',false);
  }catch(e){thinking.remove();$('chatInput').value=text;setHistoryStatus('发送失败，内容已保留，可重试：'+e.message,true);toast('发送失败：'+e.message);}
  finally{S.chatSending=false;$('chatSend').disabled=false;const next=S.chatPending;S.chatPending=null;if(next)sendChat(next);}
}
$('chatSend').onclick=()=>sendChat($('chatInput').value);
$('chatInput').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();sendChat($('chatInput').value);}};
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>sendChat(c.dataset.q));

/* 资料打开与浏览记录统一关联当前会话。 */
const historyOpenReport=openReport;
openReport=async function(name){await historyOpenReport(name);if(name)await recordVisit('report',name);};
const historyOpenSolution=openSolution;
openSolution=async function(name){await historyOpenSolution(name);if(name)await recordVisit('solution',name);};
const historyOpenCard=openCard;
openCard=async function(name){await historyOpenCard(name);if(name)await recordVisit('taskcard',name);};
const historyRtRender=rtRender;
rtRender=function(ev){historyRtRender(ev);if(ev.event==='session'&&ev.md)recordVisit('discussion',ev.md);};
const historyRtStart=$('rtStartBtn').onclick;
$('rtStartBtn').onclick=async function(){await historyRtStart();if(S.rt.active)post('/api/roundtable/start',{topic:S.rt.topic,session_id:S.history.active||''}).catch(()=>{});};
const historyStartJob=startJob;
startJob=async function(kind){await historyStartJob(kind);};
