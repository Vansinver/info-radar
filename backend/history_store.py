"""Durable, isolated translation sessions; legacy JSONL is imported without rewriting it."""
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class NewSession(BaseModel):
    title: str = Field(default="新讨论", max_length=160)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str = "legacy"
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=80)
    context: str = ""
    context_label: str = ""


class VisitRequest(BaseModel):
    kind: str
    name: str


class BriefRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    session_id: str = 'legacy'
    context: str = ''
    context_label: str = ''


class HistoryStore:
    def __init__(self, root, legacy, folders):
        self.root, self.legacy, self.folders = Path(root), Path(legacy), folders
        self.root.mkdir(parents=True, exist_ok=True)
        self.dbpath = self.root / "sessions.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT, updated TEXT,
                  context TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS messages(
                  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, ts TEXT, role TEXT,
                  content TEXT, label TEXT DEFAULT '', request_id TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS events(
                  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, ts TEXT, kind TEXT,
                  name TEXT, source TEXT DEFAULT 'visit');
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,id);
            ''')
            if not db.execute("SELECT 1 FROM meta WHERE key='legacy_imported'").fetchone():
                raw = self.legacy.read_bytes() if self.legacy.exists() else b""
                records = []
                for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if not isinstance(rec, dict) or 'content' not in rec or 'role' not in rec:
                            raise ValueError("缺少字段")
                        records.append(rec)
                    except (ValueError, TypeError) as exc:
                        raise RuntimeError(f"旧记录第 {number} 行损坏，导入已中止，原件未修改") from exc
                first, last = (records[0].get('ts', ''), records[-1].get('ts', '')) if records else (now(), now())
                db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (
                    'legacy', '旧版翻译官记录（未分会话）', first, last, '{}'))
                for rec in records:
                    db.execute("INSERT INTO messages(session_id,ts,role,content,label) VALUES(?,?,?,?,?)",
                               ('legacy', rec.get('ts', ''), rec['role'], rec['content'], rec.get('label', '')))
                # Link only exact filenames mentioned by stored messages; never guess by timestamp/topic.
                corpus = '\n'.join(str(r.get('content', '')) + '\n' + str(r.get('label', '')) for r in records)
                for kind, folder in folders.items():
                    for path in folder.glob('*.md'):
                        if path.name in corpus:
                            db.execute("INSERT INTO events(session_id,ts,kind,name,source) VALUES(?,?,?,?,?)",
                                       ('legacy', last, kind, path.name, '原记录明确提及'))
                db.execute("INSERT INTO meta VALUES('legacy_imported',?)", (hashlib.sha256(raw).hexdigest(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.dbpath, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self, sid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
            if row is None:
                raise HTTPException(404, '会话不存在，请刷新历史列表')
            result = dict(row)
            result['context'] = json.loads(result['context'])
            result['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id', (sid,))]
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE session_id=? ORDER BY id DESC', (sid,))]
            return result

    def listing(self, query=''):
        with self.connect() as db:
            rows = db.execute('''SELECT s.*, (SELECT count(*) FROM messages m WHERE m.session_id=s.id) AS count
                FROM sessions s WHERE s.title LIKE ? OR EXISTS(
                SELECT 1 FROM messages m WHERE m.session_id=s.id AND m.content LIKE ?)
                ORDER BY s.updated DESC''', ('%'+query+'%', '%'+query+'%')).fetchall()
            return [{k: r[k] for k in ('id', 'title', 'created', 'updated', 'count')} for r in rows]

    def create(self, title):
        sid, ts = uuid.uuid4().hex, now()
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (sid, title.strip() or '新讨论', ts, ts, '{}'))
        return self.session(sid)

    def visit(self, sid, kind, name):
        self.session(sid)
        if kind not in self.folders or Path(name).name != name or '/' in name or '\\' in name:
            raise HTTPException(400, '资料名称无效')
        folder = self.folders[kind].resolve()
        path = (folder / name).resolve()
        if path.parent != folder or not path.is_file() or path.suffix != '.md':
            raise HTTPException(404, '关联资料不存在')
        context = {'kind': kind, 'name': name, 'label': {'report':'报告','discussion':'圆桌实录','solution':'方案','taskcard':'任务卡'}[kind]+' '+name,
                   'text': path.read_text(encoding='utf-8')[:24000]}
        with self.connect() as db:
            db.execute('UPDATE sessions SET context=?,updated=? WHERE id=?', (json.dumps(context, ensure_ascii=False), now(), sid))
            previous = db.execute('SELECT kind,name FROM events WHERE session_id=? ORDER BY id DESC LIMIT 1', (sid,)).fetchone()
            if not previous or tuple(previous) != (kind, name):
                db.execute('INSERT INTO events(session_id,ts,kind,name) VALUES(?,?,?,?)', (sid, now(), kind, name))
        return context

    def append_pair(self, sid, question, reply, request_id):
        with self.connect() as db:
            ts = now()
            for role, content in [('user', question), ('assistant', reply)]:
                db.execute('INSERT INTO messages(session_id,ts,role,content,request_id) VALUES(?,?,?,?,?)', (sid, ts, role, content, request_id))
            db.execute('UPDATE sessions SET updated=?,title=CASE WHEN title=\'新讨论\' THEN ? ELSE title END WHERE id=?', (ts, question[:48], sid))

    def export(self, sid):
        item = self.session(sid)
        markdown = ['# '+item['title'], '', '> 旧记录时间沿用原字段；新记录带本机时区。旧版未落盘部分无法逐字恢复。', '']
        for msg in item['messages']:
            markdown += ['## '+{'user':'我','assistant':'翻译','note':'交接'}.get(msg['role'],msg['role'])+' · '+msg['ts'], '', msg['content'], '']
        markdown += ['## 关联与浏览记录', ''] + [f"- {e['ts']} · {e['kind']} · {e['name']}（{e['source']}）" for e in item['events']]
        return item, '\n'.join(markdown)


def install(host):
    app, here = host['app'], host['HERE']
    store = HistoryStore(here / 'history_data', host['CHAT_LOG'], {
        'report':host['REPORTS'], 'discussion':host['DISCUSSIONS'],
        'solution':host['SOLUTIONS'], 'taskcard':host['TASKCARDS']})
    app.state.history_store = store
    # Replace old handlers while preserving the external endpoint contract.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, 'path', '') not in ('/api/chat','/api/chat/history','/api/chat/brief')]

    @app.get('/api/history')
    def listing(q: str = ''):
        return {'sessions':store.listing(q[:300]), 'legacy_notice':'旧版记录没有会话标识，原样保留，未按内容猜测拆分。'}

    @app.post('/api/history')
    def create(body: NewSession):
        return store.create(body.title)

    @app.get('/api/history/{sid}')
    def detail(sid: str):
        result = store.session(sid)
        for msg in result['messages']:
            msg['html'] = host['render_md'](msg['content']) if msg['role']=='assistant' else ''
        return result

    @app.post('/api/history/{sid}/visit')
    def visit(sid: str, body: VisitRequest):
        return store.visit(sid, body.kind, body.name)

    @app.get('/api/history/{sid}/export')
    def export(sid: str, format: str = 'md'):
        item, md = store.export(sid)
        if format not in ('md','json'):
            raise HTTPException(400, '导出格式须为 md 或 json')
        return Response(md if format=='md' else json.dumps(item, ensure_ascii=False, indent=2),
                        media_type='text/markdown' if format=='md' else 'application/json',
                        headers={'Content-Disposition':f'attachment; filename="session-{sid}.{format}"'})

    @app.get('/api/chat/history')
    def history(session_id: str = 'legacy'):
        return detail(session_id)

    @app.post('/api/chat')
    def chat(body: ChatRequest):
        if not body.message.strip():
            raise HTTPException(400, '消息不能为空')
        # Serialize writes, model replies and request deduplication so polling/rapid clicks cannot duplicate turns.
        with store.lock:
            item = store.session(body.session_id)
            existing = next((m for m in item['messages'] if m['request_id']==body.request_id and m['role']=='assistant'), None)
            if existing:
                question = next(m for m in item['messages'] if m['request_id']==body.request_id and m['role']=='user')
                if question['content'] != body.message:
                    raise HTTPException(409, '请求编号已用于其他消息')
                reply = existing['content']
            else:
                context = item['context']
                system = host['CHAT_SYSTEM']
                if context:
                    system += '\n\n【本会话关联资料：'+context['label']+'】\n'+context['text'][:6000]
                messages = [{'role':'system','content':system}]
                messages += [{'role':m['role'],'content':m['content'][:2000]} for m in item['messages'] if m['role'] in ('user','assistant')][-8:]
                messages.append({'role':'user','content':body.message})
                reply = host['deepseek_chat'](messages)
                store.append_pair(body.session_id, body.message, reply, body.request_id)
            return {'reply':reply, 'reply_html':host['render_md'](reply), 'session_id':body.session_id}

    @app.post('/api/chat/brief')
    def brief(body: BriefRequest):
        # Compatibility for agents returning their results; bind them explicitly to a session.
        # Older callers default to the unsplit legacy session, never the user's unrelated active session.
        if body.context_label:
            for kind, folder in store.folders.items():
                match = next((p for p in folder.glob('*.md') if p.name in body.context_label), None)
                if match:
                    store.visit(body.session_id, kind, match.name)
                    break
        prompt = body.prompt
        if body.context:
            prompt += '\n\n【执行结果材料】\n'+body.context[:16000]
        return chat(ChatRequest(message=prompt, session_id=body.session_id))

    return store
