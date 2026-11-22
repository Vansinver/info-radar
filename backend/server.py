# 信息收集系统 · 公网薄壳后端（FastAPI）
# 架构沿用本机版：壳与引擎进程隔离（E1/E2/文章各自 venv 子进程），壳做编排+翻译+反馈层+任务卡。
# 公网增量：所有者 JWT 认证 / 访客虚构示例 / SQLite 任务持久化 / 私有 dataset 同步 / 任务卡领取回写。
# 红线：.env 与密钥不落持久盘、不同步、不进仓库；CORS 精确 origin 不带凭证通配；无任意命令执行接口。
import hmac
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import bleach
import httpx
import jwt
import markdown as md
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import demo_data as demo
from cloud_store import CloudStore
from history_store import HistoryStore

HERE = Path(__file__).resolve().parent                 # backend/
load_dotenv(HERE / ".env")                              # 本地开发；容器由 entrypoint 生成
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
REPORTS = DATA_DIR / "reports"
DISCUSSIONS = DATA_DIR / "discussions"
SOLUTIONS = DATA_DIR / "solutions"
TASKCARDS = DATA_DIR / "taskcards"
LEGACY = DATA_DIR / "legacy" / "chat_history.jsonl"
JOBLOGS = DATA_DIR / "joblogs"
for _d in (REPORTS, DISCUSSIONS, SOLUTIONS, TASKCARDS, JOBLOGS, DATA_DIR / "history", DATA_DIR / "legacy", DATA_DIR / "articles_work"):
    _d.mkdir(parents=True, exist_ok=True)

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API = "https://api.deepseek.com"
PY_GPTR = os.environ.get("PY_GPTR", str(HERE / "venv-gptr" / "bin" / "python"))
PY_STORM = os.environ.get("PY_STORM", str(HERE / "venv-storm" / "bin" / "python"))
OWNER_USER = os.environ.get("OWNER_USERNAME", "vansinver")
OWNER_PASS = os.environ.get("OWNER_PASSWORD", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
PAGES_ORIGIN = os.environ.get("PAGES_ORIGIN", "https://vansinver.github.io")
BUILD_SHA = os.environ.get("BUILD_SHA", "dev")
HF_DATASET = os.environ.get("HF_DATASET_REPO", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# 引擎工作目录软链（HERE 相对路径 → 持久盘），与 entrypoint 一致，本地开发也生效
for _d in ("reports", "discussions", "articles_work"):
    _link = HERE / _d
    if not _link.exists():
        try:
            _link.symlink_to(DATA_DIR / _d, target_is_directory=True)
        except OSError:
            pass


def ensure_engine_env():
    """从运行时环境生成引擎 .env（容器内临时文件；cloud_store 排除 .env，绝不外传）。"""
    content = (
        f"DEEPSEEK_API_KEY={KEY}\n"
        f"RETRIEVER={os.environ.get('RETRIEVER', 'deepseek')}\n"
        f"FAST_LLM={os.environ.get('FAST_LLM', 'deepseek:deepseek-flash')}\n"
        f"SMART_LLM={os.environ.get('SMART_LLM', 'deepseek:deepseek-flash')}\n"
        f"EMBEDDING={os.environ.get('EMBEDDING', 'huggingface:all-MiniLM-L6-v2')}\n"
        f"HF_ENDPOINT={os.environ.get('HF_ENDPOINT', 'https://huggingface.co')}\n"
    )
    (HERE / ".env").write_text(content, encoding="utf-8")


ensure_engine_env()

app = FastAPI(title="信息收集系统 · 公网薄壳")
_origins = [o for o in [PAGES_ORIGIN, os.environ.get("SPACE_ORIGIN", "")] if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------- 持久化同步 ----------
cloud = CloudStore(DATA_DIR, HF_DATASET, HF_TOKEN)
cloud.pull()

# ---------- 历史会话存储（旧 JSONL 只读导入，原件不改） ----------
store = HistoryStore(DATA_DIR / "history", LEGACY, {
    "report": REPORTS, "discussion": DISCUSSIONS, "solution": SOLUTIONS, "taskcard": TASKCARDS})

# ---------- 任务持久化（重启可恢复；running → interrupted） ----------
JOBS_DB = DATA_DIR / "jobs.sqlite3"


@contextmanager
def jobs_db():
    db = sqlite3.connect(JOBS_DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


with jobs_db() as _db:
    _db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, kind TEXT, arg TEXT, status TEXT, result TEXT,
          exit INTEGER, started TEXT, finished TEXT, session_id TEXT, logfile TEXT);
    """)
    _db.execute("UPDATE jobs SET status='interrupted', finished=? WHERE status='running'",
                (datetime.now().astimezone().isoformat(timespec="seconds"),))


# ---------- 认证 ----------
def make_token():
    return jwt.encode({"sub": OWNER_USER, "exp": int(time.time()) + 7 * 86400},
                      JWT_SECRET, algorithm="HS256")


def token_ok(tok):
    if not JWT_SECRET or not tok:
        return False
    try:
        payload = jwt.decode(tok, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub") == OWNER_USER
    except jwt.PyJWTError:
        return False


@app.middleware("http")
async def auth_ctx(request: Request, call_next):
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.startswith("Bearer ") else ""
    request.state.owner = token_ok(tok)
    return await call_next(request)


def require_owner(request: Request):
    if not request.state.owner:
        raise HTTPException(401, "需要登录所有者账号")


# ---------- 限流（单实例内存令牌桶） ----------
_RL = {}
_RL_LOCK = threading.Lock()


def rate_limit(request: Request, key: str, limit: int, window: int):
    ip = request.client.host if request.client else "unknown"
    bucket_key = (ip, key)
    now = time.time()
    with _RL_LOCK:
        dq = _RL.setdefault(bucket_key, deque())
        while dq and dq[0] < now - window:
            dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(429, "操作过于频繁，请稍后再试")
        dq.append(now)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    rate_limit(request, "login", 5, 60)
    if not OWNER_PASS or not JWT_SECRET:
        raise HTTPException(503, "服务端未配置所有者凭证")
    ok_user = hmac.compare_digest(body.username, OWNER_USER)
    ok_pass = hmac.compare_digest(body.password, OWNER_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(401, "用户名或密码错误")
    return {"token": make_token(), "username": OWNER_USER}


@app.get("/api/me")
def me(request: Request):
    require_owner(request)
    return {"username": OWNER_USER}


# ---------- markdown 渲染（bleach 消毒） ----------
_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "strong", "em",
         "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "br", "hr"]


def render_md(text: str) -> str:
    text = re.sub(r'(?<![\("\w])(https?://[^\s<>\)）]+)', r'<\1>', text)
    html = md.markdown(text, extensions=["tables", "fenced_code"])
    html = bleach.clean(html, tags=_TAGS, attributes={"a": ["href", "title"]}, strip=True)
    return html.replace('<a href=', '<a target="_blank" rel="noopener" href=')


def _safe(path: Path, name: str) -> Path:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    p = (path / name).resolve()
    if p.parent != path.resolve() or not p.is_file():
        raise HTTPException(404, "文件不存在")
    return p


# ---------- DeepSeek 直连 ----------
def deepseek_chat(messages, json_mode=False, timeout=120):
    if not KEY:
        raise HTTPException(500, "未配置 DEEPSEEK_API_KEY")
    body = {"model": "deepseek-flash", "messages": messages,
            "thinking": {"type": "disabled"}, "temperature": 0.7}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(API + "/v1/chat/completions", json=body,
                   headers={"Authorization": f"Bearer {KEY}"}, timeout=timeout)
    if r.status_code != 200:
        raise HTTPException(502, f"DeepSeek 返回 {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


# ---------- 一次性任务（E1 / 文章），SQLite 持久化 ----------
def _job_reader(jid, proc, logfile):
    result = None
    with open(logfile, "a", encoding="utf-8") as lf:
        for line in proc.stdout:
            line = line.rstrip()
            lf.write(line + "\n")
            lf.flush()
            m = re.search(r"报告已落盘：(.+)", line)
            if m:
                result = Path(m.group(1).strip()).name
    proc.wait()
    status = "done" if (proc.returncode == 0 and result) else "failed"
    with jobs_db() as db:
        db.execute("UPDATE jobs SET status=?, result=?, exit=?, finished=? WHERE id=?",
                   (status, result, proc.returncode,
                    datetime.now().astimezone().isoformat(timespec="seconds"), jid))
    cloud.push()


def spawn_job(kind, script, py, arg, session_id=""):
    jid = uuid.uuid4().hex[:8]
    logfile = str(JOBLOGS / f"{jid}.log")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([py, str(HERE / script), arg], cwd=str(HERE),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env)
    with jobs_db() as db:
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (jid, kind, arg, "running", None, None,
                    datetime.now().astimezone().isoformat(timespec="seconds"), None, session_id, logfile))
    threading.Thread(target=_job_reader, args=(jid, proc, logfile), daemon=True).start()
    return jid


class JobIn(BaseModel):
    query: str
    session_id: str = ""


@app.post("/api/jobs/e1")
def start_e1(body: JobIn, request: Request):
    require_owner(request)
    rate_limit(request, "jobs", 5, 3600)
    if not body.query.strip():
        raise HTTPException(400, "问题不能为空")
    return {"job_id": spawn_job("e1", "run_e1.py", PY_GPTR, body.query.strip(), body.session_id)}


@app.post("/api/jobs/article")
def start_article(body: JobIn, request: Request):
    require_owner(request)
    rate_limit(request, "jobs", 5, 3600)
    if not body.query.strip():
        raise HTTPException(400, "主题不能为空")
    return {"job_id": spawn_job("article", "run_article.py", PY_STORM, body.query.strip(), body.session_id)}


@app.get("/api/jobs")
def list_jobs(request: Request):
    if not request.state.owner:
        return []
    with jobs_db() as db:
        rows = db.execute("SELECT id,kind,arg,status,result,started,session_id FROM jobs ORDER BY started DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/jobs/{jid}")
def job_state(jid: str, request: Request):
    require_owner(request)
    with jobs_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise HTTPException(404, "任务不存在")
    job = dict(row)
    tail = []
    lf = Path(job["logfile"])
    if lf.exists():
        tail = lf.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
    return {"id": jid, "kind": job["kind"], "status": job["status"], "result": job["result"], "tail": tail}


# ---------- 圆桌（单会话，JSON-lines 子进程；重启后状态归零，实录可读） ----------
RT = {"proc": None, "events": [], "status": "idle", "topic": "", "session_id": "", "lock": threading.Lock()}


def _rt_reader(proc):
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        with RT["lock"]:
            RT["events"].append(ev)
            if ev.get("event") == "ready":
                RT["status"] = "ready"
            elif ev.get("event") == "status":
                RT["status"] = "working"
            elif ev.get("event") == "bye":
                RT["status"] = "stopped"
            sid = RT["session_id"]
        if sid and ev.get("event") in ("session", "report") and ev.get("md"):
            try:
                store.visit(sid, "discussion", ev["md"])
                cloud.push()
            except Exception:
                pass
    proc.wait()
    with RT["lock"]:
        if RT["status"] not in ("stopped",):
            RT["status"] = "exited"


def _rt_send(obj):
    proc = RT["proc"]
    if proc is None or proc.poll() is not None:
        raise HTTPException(409, "圆桌未运行")
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


class RTStart(BaseModel):
    topic: str
    background: str = ""
    session_id: str = ""


class RTSay(BaseModel):
    text: str = ""


@app.post("/api/roundtable/start")
def rt_start(body: RTStart, request: Request):
    require_owner(request)
    rate_limit(request, "jobs", 5, 3600)
    if not body.topic.strip():
        raise HTTPException(400, "话题不能为空")
    with RT["lock"]:
        if RT["proc"] is not None and RT["proc"].poll() is None:
            raise HTTPException(409, "已有圆桌在进行，请先结束")
        err = open(JOBLOGS / "e2-api-err.log", "w", encoding="utf-8")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen([PY_STORM, str(HERE / "run_e2_api.py")], cwd=str(HERE),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                text=True, encoding="utf-8", errors="replace", env=env)
        RT.update(proc=proc, events=[], status="starting", topic=body.topic.strip(), session_id=body.session_id)
    threading.Thread(target=_rt_reader, args=(proc,), daemon=True).start()
    _rt_send({"cmd": "start", "topic": body.topic.strip(), "background": body.background})
    return {"ok": True}


@app.get("/api/roundtable/state")
def rt_state(request: Request, since: int = 0):
    if not request.state.owner:
        return {"status": "idle", "topic": "", "events": [], "total": 0}
    with RT["lock"]:
        return {"status": RT["status"], "topic": RT["topic"],
                "events": RT["events"][since:], "total": len(RT["events"])}


@app.post("/api/roundtable/say")
def rt_say(body: RTSay, request: Request):
    require_owner(request)
    _rt_send({"cmd": "say", "text": body.text})
    return {"ok": True}


@app.post("/api/roundtable/next")
def rt_next(request: Request):
    require_owner(request)
    _rt_send({"cmd": "next"})
    return {"ok": True}


@app.post("/api/roundtable/report")
def rt_report(request: Request):
    require_owner(request)
    _rt_send({"cmd": "report"})
    return {"ok": True}


@app.post("/api/roundtable/stop")
def rt_stop(request: Request):
    require_owner(request)
    proc = RT["proc"]
    if proc is None or proc.poll() is not None:
        with RT["lock"]:
            RT["status"] = "stopped"
        return {"ok": True}
    try:
        _rt_send({"cmd": "quit"})
    except Exception:
        pass

    def _kill():
        if proc.poll() is None:
            proc.terminate()
    threading.Timer(6, _kill).start()
    with RT["lock"]:
        RT["status"] = "stopped"
    return {"ok": True}


# ---------- 报告 / 圆桌实录 / 方案 / 反馈层（访客=虚构示例） ----------
@app.get("/api/reports")
def list_reports(request: Request):
    if not request.state.owner:
        return demo.demo_reports()
    items = []
    for p in sorted(REPORTS.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({"name": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M"),
                      "size": p.stat().st_size,
                      "has_feedback": (REPORTS / (p.stem + ".feedback.json")).exists()})
    return items


@app.get("/api/reports/{name}")
def get_report(name: str, request: Request):
    if not request.state.owner:
        if name in demo.DEMO_TEXTS:
            return {"name": name, "html": render_md(demo.DEMO_TEXTS[name]), "md": demo.DEMO_TEXTS[name]}
        raise HTTPException(404, "文件不存在")
    p = _safe(REPORTS, name)
    text = p.read_text(encoding="utf-8")
    return {"name": name, "html": render_md(text), "md": text}


@app.get("/api/discussions")
def list_discussions(request: Request):
    if not request.state.owner:
        return demo.demo_discussions()
    if not DISCUSSIONS.exists():
        return []
    return [{"name": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")}
            for p in sorted(DISCUSSIONS.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)]


@app.get("/api/discussions/{name}")
def get_discussion(name: str, request: Request):
    if not request.state.owner:
        if name in demo.DEMO_TEXTS:
            return {"name": name, "html": render_md(demo.DEMO_TEXTS[name]), "md": demo.DEMO_TEXTS[name]}
        raise HTTPException(404, "文件不存在")
    p = _safe(DISCUSSIONS, name)
    text = p.read_text(encoding="utf-8")
    if name.endswith(".jsonl"):
        return {"name": name, "raw": text}
    return {"name": name, "html": render_md(text), "md": text}


@app.get("/api/solutions")
def list_solutions(request: Request):
    if not request.state.owner:
        return demo.demo_solutions()
    if not SOLUTIONS.exists():
        return []
    return [{"name": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")}
            for p in sorted(SOLUTIONS.glob("*.md"))]


@app.get("/api/solutions/{name}")
def get_solution(name: str, request: Request):
    if not request.state.owner:
        if name in demo.DEMO_TEXTS:
            return {"name": name, "html": render_md(demo.DEMO_TEXTS[name]), "md": demo.DEMO_TEXTS[name]}
        raise HTTPException(404, "文件不存在")
    p = _safe(SOLUTIONS, name)
    text = p.read_text(encoding="utf-8")
    return {"name": name, "html": render_md(text), "md": text}


FB_SYSTEM = (
    "你是信息收集系统的反馈层抽取器。读研究报告，输出严格 JSON（不要多余文字）：\n"
    '{"one_line_summary":"一句话概括报告说了什么",'
    '"decision_clues":[{"clue":"可能改变决策的线索","why":"为什么重要","source":"报告内对应出处URL，没有则空串"}],'
    '"open_questions":["报告未解决/存疑的问题"],'
    '"next_queries":["值得下一轮检索的具体问题（可直接当搜索query）"]}\n'
    "decision_clues 最多 5 条，next_queries 最多 4 条。用简体中文。只依据报告内容，不编造。")


@app.post("/api/reports/{name}/feedback")
def make_feedback(name: str, request: Request):
    require_owner(request)
    rate_limit(request, "chat", 30, 60)
    p = _safe(REPORTS, name)
    text = p.read_text(encoding="utf-8")[:12000]
    raw = deepseek_chat([{"role": "system", "content": FB_SYSTEM},
                         {"role": "user", "content": text}], json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, "反馈层 JSON 解析失败：" + raw[:200])
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    data["report"] = name
    (REPORTS / (p.stem + ".feedback.json")).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    cloud.push()
    return data


@app.get("/api/reports/{name}/feedback")
def get_feedback(name: str, request: Request):
    require_owner(request)
    p = _safe(REPORTS, name)
    sidecar = REPORTS / (p.stem + ".feedback.json")
    if not sidecar.exists():
        raise HTTPException(404, "尚未生成反馈层")
    return json.loads(sidecar.read_text(encoding="utf-8"))


# ---------- 历史会话（访客=虚构示例会话） ----------
@app.get("/api/history")
def history_listing(request: Request, q: str = ""):
    if not request.state.owner:
        return demo.demo_history_listing()
    return {"sessions": store.listing(q[:300]),
            "legacy_notice": "旧版记录没有会话标识，原样保留，未按内容猜测拆分。"}


class NewSession(BaseModel):
    title: str = "新讨论"


@app.post("/api/history")
def history_create(body: NewSession, request: Request):
    require_owner(request)
    item = store.create(body.title[:160])
    cloud.push()
    return item


@app.get("/api/history/{sid}")
def history_detail(sid: str, request: Request):
    if not request.state.owner:
        if sid == demo.DEMO_SESSION_ID:
            return demo.demo_session(render_md)
        raise HTTPException(404, "会话不存在")
    result = store.session(sid)
    for msg in result["messages"]:
        msg["html"] = render_md(msg["content"]) if msg["role"] == "assistant" else ""
    return result


class VisitIn(BaseModel):
    kind: str
    name: str


@app.post("/api/history/{sid}/visit")
def history_visit(sid: str, body: VisitIn, request: Request):
    require_owner(request)
    ctx = store.visit(sid, body.kind, body.name)
    cloud.push()
    return ctx


@app.get("/api/history/{sid}/export")
def history_export(sid: str, request: Request, format: str = "md"):
    require_owner(request)
    if format not in ("md", "json"):
        raise HTTPException(400, "导出格式须为 md 或 json")
    item, mdtext = store.export(sid)
    return Response(mdtext if format == "md" else json.dumps(item, ensure_ascii=False, indent=2),
                    media_type="text/markdown" if format == "md" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="session-{sid}.{format}"'})


# ---------- 右栏翻译聊天 ----------
CHAT_SYSTEM = (
    "你是信息收集系统的『翻译』角色，坐在用户旁边答疑。职责：把专业内容压成大白话；"
    "用户问什么答什么；基于给出的左栏上下文回答，上下文没有的就直说不确定，不编造。"
    "回答用简体中文，简洁、可扫读，少堆术语；必要时指出下一步可以做什么。")


class ChatIn(BaseModel):
    message: str
    session_id: str = "legacy"
    request_id: str = ""
    context: str = ""
    context_label: str = ""


@app.get("/api/chat/history")
def chat_history(request: Request, session_id: str = "legacy"):
    return history_detail(session_id, request)


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    require_owner(request)
    rate_limit(request, "chat", 30, 60)
    if not body.message.strip():
        raise HTTPException(400, "消息不能为空")
    rid = body.request_id or uuid.uuid4().hex
    with store.lock:
        item = store.session(body.session_id)
        existing = next((m for m in item["messages"] if m["request_id"] == rid and m["role"] == "assistant"), None)
        if existing:
            question = next(m for m in item["messages"] if m["request_id"] == rid and m["role"] == "user")
            if question["content"] != body.message:
                raise HTTPException(409, "请求编号已用于其他消息")
            reply = existing["content"]
        else:
            context = item["context"]
            system = CHAT_SYSTEM
            if context:
                system += "\n\n【本会话关联资料：" + context["label"] + "】\n" + context["text"][:6000]
            elif body.context:
                system += f"\n\n【用户当前正在看的内容：{body.context_label}】\n{body.context[:6000]}"
            messages = [{"role": "system", "content": system}]
            messages += [{"role": m["role"], "content": m["content"][:2000]}
                         for m in item["messages"] if m["role"] in ("user", "assistant")][-8:]
            messages.append({"role": "user", "content": body.message})
            reply = deepseek_chat(messages)
            store.append_pair(body.session_id, body.message, reply, rid)
            cloud.push()
    return {"reply": reply, "reply_html": render_md(reply), "session_id": body.session_id}


class BriefIn(BaseModel):
    prompt: str
    session_id: str = "legacy"
    context: str = ""
    context_label: str = ""


@app.post("/api/chat/brief")
def chat_brief(body: BriefIn, request: Request):
    require_owner(request)
    if body.context_label:
        for kind, folder in store.folders.items():
            match = next((p for p in folder.glob("*.md") if p.name in body.context_label), None)
            if match:
                store.visit(body.session_id, kind, match.name)
                break
    prompt = body.prompt
    if body.context:
        prompt += "\n\n【执行结果材料】\n" + body.context[:16000]
    return chat(ChatIn(message=prompt, session_id=body.session_id), request)


# ---------- 任务卡（云端交接：生成→待执行→领取→回写；本机执行 Agent 经 HTTPS 同步） ----------
CLOUD_INBOX = TASKCARDS / "_inbox.md"
TC_SYSTEM = (
    "你是信息收集系统的执行交接件生成器。把给出的上下文（报告/圆桌实录/讨论）整理成一张可执行任务卡，"
    "输出纯 Markdown（不要代码围栏包裹），格式：\n"
    "---\nid: TC-<日期>-<两位序号>\ntitle: <短题>\nstatus: draft\ncreated: <日期>\nsource: <上下文来源文件名>\n---\n"
    "# <id> · <title>\n## 目标\n## 步骤（每步含可执行命令或具体动作；需新样本/新授权/余额的步骤标【门槛】）\n"
    "## 验收断言（可判真假的句子）\n## 证据指针（上下文内真实文件路径/URL）\n## 风险与授权门槛\n"
    "只依据上下文，不编造路径与数据；简体中文；步骤≤8。")


def _card_meta(text):
    m = re.search(r"^status:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else "unknown"


def _inbox_append(name):
    if not CLOUD_INBOX.exists():
        CLOUD_INBOX.write_text("# 云端待执行任务卡 inbox\n\n"
                               "> 公网薄壳生成/交接的任务卡在此登记。本机执行 Agent 经 /api/taskcards/pending 领取，\n"
                               "> 完成后经 /api/taskcards/{name}/writeback 回写。云端不写本机 Obsidian、无任意命令接口。\n",
                               encoding="utf-8")
    existing = CLOUD_INBOX.read_text(encoding="utf-8")
    if name in existing:
        return
    with CLOUD_INBOX.open("a", encoding="utf-8") as f:
        f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {name}\n")


@app.get("/api/taskcards")
def list_taskcards(request: Request):
    if not request.state.owner:
        return demo.demo_taskcards()
    items = []
    for p in sorted(TASKCARDS.glob("TC-*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({"name": p.name, "status": _card_meta(p.read_text(encoding="utf-8")),
                      "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")})
    return items


@app.get("/api/taskcards/pending")
def taskcards_pending(request: Request):
    require_owner(request)
    out = []
    for p in sorted(TASKCARDS.glob("TC-*.md")):
        st = _card_meta(p.read_text(encoding="utf-8"))
        if st in ("待执行", "执行中"):
            out.append({"name": p.name, "status": st})
    return out


@app.get("/api/taskcards/{name}")
def get_taskcard(name: str, request: Request):
    if not request.state.owner:
        if name in demo.DEMO_TEXTS:
            return {"name": name, "status": "待执行", "html": render_md(demo.DEMO_TEXTS[name]), "md": demo.DEMO_TEXTS[name]}
        raise HTTPException(404, "文件不存在")
    p = _safe(TASKCARDS, name)
    text = p.read_text(encoding="utf-8")
    return {"name": name, "status": _card_meta(text), "html": render_md(text), "md": text}


@app.get("/api/taskcards/{name}/export")
def taskcard_export(name: str, request: Request):
    require_owner(request)
    p = _safe(TASKCARDS, name)
    return Response(p.read_text(encoding="utf-8"), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class CardIn(BaseModel):
    context: str = ""
    context_label: str = ""


@app.post("/api/taskcards")
def make_taskcard(body: CardIn, request: Request):
    require_owner(request)
    rate_limit(request, "chat", 30, 60)
    if not body.context.strip():
        raise HTTPException(400, "没有可用上下文（先打开报告/圆桌/方案）")
    raw = deepseek_chat([{"role": "system", "content": TC_SYSTEM},
                         {"role": "user", "content": f"【来源：{body.context_label}】\n{body.context[:12000]}"}])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    if not raw.startswith("---"):
        raise HTTPException(502, "任务卡格式不符（缺 frontmatter）：" + raw[:120])
    seq = len(list(TASKCARDS.glob("TC-*.md"))) + 1
    day = datetime.now().strftime("%Y%m%d")
    title = (re.search(r"^title:\s*(.+)$", raw, re.M) or [None, "未命名"])[1].strip()
    slug = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:24]
    name = f"TC-{day}-{seq:02d}_{slug}.md"
    raw = re.sub(r"^status:\s*.+$", "status: 待执行", raw, count=1, flags=re.M)
    (TASKCARDS / name).write_text(raw, encoding="utf-8")
    _inbox_append(name)
    cloud.push()
    return {"name": name, "status": "待执行"}


@app.post("/api/taskcards/{name}/handoff")
def handoff_taskcard(name: str, request: Request):
    require_owner(request)
    p = _safe(TASKCARDS, name)
    text = p.read_text(encoding="utf-8")
    if not re.search(r"^status:\s*.+$", text, re.M):
        raise HTTPException(400, "卡片缺 status 字段")
    text = re.sub(r"^status:\s*.+$", "status: 待执行", text, count=1, flags=re.M)
    p.write_text(text, encoding="utf-8")
    _inbox_append(name)
    cloud.push()
    return {"name": name, "status": "待执行"}


class ClaimIn(BaseModel):
    agent: str = "local-executor"


@app.post("/api/taskcards/{name}/claim")
def claim_taskcard(name: str, body: ClaimIn, request: Request):
    require_owner(request)
    p = _safe(TASKCARDS, name)
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"^status:\s*.+$", "status: 执行中", text, count=1, flags=re.M)
    if "claimed_by:" not in text:
        text = re.sub(r"^(status:\s*.+)$", r"\1\nclaimed_by: " + body.agent +
                      "\nclaimed_at: " + datetime.now().strftime("%Y-%m-%d %H:%M"), text, count=1, flags=re.M)
    p.write_text(text, encoding="utf-8")
    cloud.push()
    return {"name": name, "status": "执行中", "claimed_by": body.agent}


class WritebackIn(BaseModel):
    status: str = "已完成"
    record: str = ""
    agent: str = "local-executor"


@app.post("/api/taskcards/{name}/writeback")
def writeback_taskcard(name: str, body: WritebackIn, request: Request):
    require_owner(request)
    if body.status not in ("执行中", "已完成", "已验收", "受阻"):
        raise HTTPException(400, "非法状态")
    p = _safe(TASKCARDS, name)
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"^status:\s*.+$", "status: " + body.status, text, count=1, flags=re.M)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    text += f"\n\n## 执行回写 · {stamp} · {body.agent}\n\n{body.record}\n"
    p.write_text(text, encoding="utf-8")
    cloud.push()
    return {"name": name, "status": body.status}


# ---------- 健康 / 前端 ----------
@app.get("/api/health")
def health(request: Request):
    return {"ok": True, "key_present": bool(KEY),
            "reports": len(list(REPORTS.glob("*.md"))) if request.state.owner else 1,
            "version": BUILD_SHA, "persistence": cloud.mode,
            "auth_required": True, "owner": request.state.owner}


FRONTEND = HERE.parent / "frontend"
if FRONTEND.exists():
    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")

cloud.start_background(45)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")), log_level="warning")
