/* Durable history UI（公网适配版）。No automatic messages or model calls. */
const H={id:null, context:null, ready:false, busy:false, token:0, query:'', all:[], timer:null};
const oldContext=currentContext;
currentContext=function(){
  if(S.tab==='rt' && S.rt.active) return oldContext();
  return H.context||{label:'',text:''};
};
function historyStatus(text,error=false){
  $('historyStatus').textContent=text; $('historyStatus').style.color=error?'var(--danger)':'var(--sub)';
  $('historyRetry').hidden=!error;
}
function setChatEnabled(yes){
  $('chatSend').disabled=!yes; $('chatInput').disabled=!yes;
  document.querySelectorAll('.chip').forEach(x=>{x.style.pointerEvents=yes?'':'none';x.style.opacity=yes?'':'0.45';});
}
function historyError(e){historyStatus('历史加载失败：'+e.message+'。记录尚未确认，请重试。',true);setChatEnabled(false);}
function defaultSession(){ return localStorage.getItem('radar_history_session') || (window.__guest?'demo':'legacy'); }
function bindExport(el, sid, fmt){
  el.href='#';
  el.onclick=async(e)=>{
    e.preventDefault();
    if(window.__guest){ toast('示例模式：登录后可导出真实会话'); return; }
    try{
      const t=authToken(); const h=t?{'Authorization':'Bearer '+t}:{};
      const r=await fetch((window.API_BASE||'')+'/api/history/'+encodeURIComponent(sid)+'/export?format='+fmt,{headers:h});
      if(!r.ok){ toast('导出失败 HTTP '+r.status); return; }
      const blob=await r.blob(); const u=URL.createObjectURL(blob);
      const a=document.createElement('a'); a.href=u; a.download='session-'+sid+'.'+fmt; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(u),60000);
    }catch(e){ toast('导出错误：'+e.message); }
  };
}
async function historyList(){
  const result=await api('/api/history?q='+encodeURIComponent($('historySearch').value.trim()));
  const list=$('sessionList'); list.replaceChildren();
  if(!result.sessions.length){list.textContent='没有匹配会话。可以换关键词，或新建讨论。';return;}
  for(const s of result.sessions){
    const b=document.createElement('button'); b.className='session-item'+(s.id===H.id?' selected':'');
    const title=document.createElement('strong'); title.textContent=s.title;
    const detail=document.createElement('small'); detail.textContent=s.count+' 条 · '+s.created+' → '+s.updated;
    b.append(title,detail); b.onclick=()=>chooseSession(s.id);list.appendChild(b);
  }
}
function historyFilter(){
  const q=$('messageSearch').value.trim().toLowerCase();
  const messages=q?H.all.filter(m=>String(m.content).toLowerCase().includes(q)):H.all;
  $('historyMessageCount').textContent=q?'匹配 '+messages.length+' / '+H.all.length+' 条':'共 '+H.all.length+' 条';
  $('historyMessages').innerHTML=messages.length?messages.map(msgHtml).join(''):'<p class="empty">没有匹配记录</p>';
}
function renderRelated(item){
  const list=$('relatedFiles');list.replaceChildren();
  const seen=new Set();
  for(const ev of item.events){
    const key=ev.kind+':'+ev.name;if(seen.has(key))continue;seen.add(key);
    const b=document.createElement('button');b.className='related-file';b.textContent=ev.name+' · '+ev.source;
    b.onclick=()=>showRelated(ev.kind,ev.name).catch(e=>toast(e.message));list.appendChild(b);
  }
  if(!seen.size)list.textContent='暂无关联资料。打开报告、圆桌实录、方案或任务卡后会自动记录。';
  $('browseEvents').textContent=item.events.slice(0,30).map(e=>e.ts+' · '+e.kind+' · '+e.name+'（'+e.source+'）').join('\n')||'尚无浏览记录';
}
async function chooseSession(id){
  if(H.busy)return toast('翻译正在回复，请等回复完成后切换会话');
  const token=++H.token;H.ready=false;setChatEnabled(false);historyStatus('正在恢复会话…');
  try{
    const item=await api('/api/history/'+encodeURIComponent(id));if(token!==H.token)return;
    H.id=id;H.context=item.context?.text?item.context:null;H.all=item.messages;H.ready=true;
    localStorage.setItem('radar_history_session',id);
    $('activeSession').textContent=item.title;
    $('historyTitle').textContent=item.title;
    $('historyMeta').textContent=item.created+' → '+item.updated+(id==='legacy'?' · 旧版未按会话拆分；更早未落盘部分只有交接摘要。':'');
    $('messageSearch').value='';
    bindExport($('exportMd'), id, 'md');
    bindExport($('exportJson'), id, 'json');
    renderHistory(item.messages);historyFilter();renderRelated(item);updateCtx();
    historyStatus('已恢复 '+item.messages.length+' 条 · 新消息会保存在当前会话');setChatEnabled(true);
    await historyList();
  }catch(e){if(token===H.token)historyError(e);}
}
async function createSession(){
  if(window.__guest)return toast('示例模式：登录后即可新建讨论');
  if(H.busy)return toast('请等当前回复完成');
  try{
    const item=await post('/api/history',{title:$('newSessionTitle').value.trim()||'新讨论'});
    $('newSessionTitle').value='';await chooseSession(item.id);$('chatInput').focus();
  }catch(e){historyError(e);}
}
async function recordVisit(kind,name){
  if(!H.ready||H.busy||window.__guest)return;
  const sid=H.id;
  const context=await post('/api/history/'+sid+'/visit',{kind,name});
  if(H.id!==sid)return;
  H.context=context;updateCtx();
  const item=await api('/api/history/'+sid);if(H.id===sid)renderRelated(item);
}
async function showRelated(kind,name){
  const endpoints={report:'reports',discussion:'discussions',solution:'solutions',taskcard:'taskcards'};
  const doc=await api('/api/'+endpoints[kind]+'/'+encodeURIComponent(name));
  $('historyDocument').innerHTML=doc.html;
  $('historyDocumentTitle').textContent=name;
  $('historyDocumentPanel').hidden=false;
  await recordVisit(kind,name);$('historyDocumentPanel').scrollIntoView({block:'nearest'});
}
const historyOpenReport=openReport;
openReport=async function(name){const token=H.token;await historyOpenReport(name);if(token===H.token)await recordVisit('report',name);};
const historyOpenSolution=openSolution;
openSolution=async function(name){const token=H.token;await historyOpenSolution(name);if(token===H.token)await recordVisit('solution',name);};
const historyOpenCard=openCard;
openCard=async function(name){const token=H.token;await historyOpenCard(name);if(token===H.token)await recordVisit('taskcard',name);};
$('repSelect').onchange=e=>openReport(e.target.value).catch(e=>toast(e.message));
$('solSelect').onchange=e=>openSolution(e.target.value).catch(e=>toast(e.message));
$('tcSelect').onchange=e=>openCard(e.target.value).catch(e=>toast(e.message));

chatSync=async function(){
  if(!H.ready||H.busy)return;
  const sid=H.id,token=H.token;
  try{
    const item=await api('/api/history/'+sid);
    if(token!==H.token||H.busy)return;
    if(item.messages.length!==H.all.length){
      H.all=item.messages;renderHistory(item.messages);historyFilter();
      historyStatus('已同步 '+item.messages.length+' 条');
    }
  }catch(e){historyError(e);}
};
sendChat=async function(text){
  if(!text||H.busy||!H.ready)return;
  if(window.__guest){toast('示例模式：登录后即可向翻译提问');return;}
  H.busy=true;setChatEnabled(false);$('newHistorySession').disabled=true;
  const sid=H.id;
  addMsg('user',text);historyStatus('翻译正在回复…');
  const previous=H.pending;
  const requestId=previous&&previous.sid===sid&&previous.text===text?previous.id:(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());
  H.pending={sid,text,id:requestId};
  try{
    if(S.rt.active&&S.rt.md){
      H.context=await post('/api/history/'+sid+'/visit',{kind:'discussion',name:S.rt.md});
      updateCtx();
    }
    await post('/api/chat',{message:text,session_id:sid,request_id:requestId});
    H.pending=null;
    $('chatInput').value='';
    H.busy=false;await chooseSession(sid);
  }catch(e){
    H.busy=false;renderHistory(H.all);setChatEnabled(true);
    historyStatus('发送失败：'+e.message+'。输入已保留，未伪造回复。',true);
  }finally{H.busy=false;$('newHistorySession').disabled=false;}
};
$('showHistory').onclick=()=>document.querySelector('[data-tab="history"]').click();
$('historyRetry').onclick=()=>chooseSession(H.id||defaultSession());
$('historyRefresh').onclick=()=>chooseSession(H.id||defaultSession());
$('newHistorySession').onclick=createSession;
$('historySearch').oninput=()=>{clearTimeout(H.timer);H.timer=setTimeout(()=>historyList().catch(historyError),180);};
$('messageSearch').oninput=historyFilter;
$('newSessionTitle').onkeydown=e=>{if(e.key==='Enter')createSession();};
$('historyCloseDocument').onclick=()=>{$('historyDocumentPanel').hidden=true;};
document.querySelector('[data-tab="history"]').addEventListener('click',()=>historyList().catch(historyError));
async function historyBoot(){
  H.ready=false;setChatEnabled(false);
  const saved=localStorage.getItem('radar_history_session');
  if(saved){
    try{await api('/api/history/'+encodeURIComponent(saved));}catch(e){
      if(!String(e.message).includes('会话不存在')){historyError(e);return;}
      localStorage.removeItem('radar_history_session');toast('先前会话不存在，已返回默认记录');
    }
  }
  await chooseSession(defaultSession());
  await loadHistoryAssets();
}
async function loadHistoryAssets(){
  const groups=await Promise.all(['reports','discussions','solutions','taskcards'].map(x=>api('/api/'+x)));
  const kinds=['report','discussion','solution','taskcard'], labels=['报告','圆桌实录','方案','任务卡'];
  $('historyAsset').replaceChildren();
  groups.forEach((items,i)=>{
    const group=document.createElement('optgroup');group.label=labels[i];
    items.forEach(item=>{const option=document.createElement('option');option.value=JSON.stringify({kind:kinds[i],name:item.name});option.textContent=item.name;group.appendChild(option);});
    $('historyAsset').appendChild(group);
  });
}
$('historyAssetOpen').onclick=()=>{
  if(!$('historyAsset').value)return;
  const ref=JSON.parse($('historyAsset').value);showRelated(ref.kind,ref.name).catch(e=>toast(e.message));
};
