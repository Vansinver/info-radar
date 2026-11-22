# E2 圆桌 JSON-lines 适配器：供薄壳以子进程驱动（stdin 收命令，stdout 发事件）
# 协议：
#   入 {"cmd":"start","topic":"…","background":"可选报告全文"} / {"cmd":"say","text":"…"}
#      {"cmd":"next"} / {"cmd":"report"} / {"cmd":"quit"}
#   出 {"event":"status|turn|ready|report|error|bye", …}
# 库的所有打印重定向到 stderr，stdout 只走纯 JSON。
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
sys.path.insert(0, str(HERE / "storm-deepseek-rm"))
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

_REAL_OUT = sys.stdout
sys.stdout = sys.stderr  # 库打印/litellm 噪音全走 stderr（薄壳落 err 日志）


def emit(obj):
    _REAL_OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _REAL_OUT.flush()


from deepseek_search_rm import DeepSeekSearchRM  # noqa: E402
from local_encoder import LocalEncoder  # noqa: E402
import knowledge_storm.collaborative_storm.engine as cs_engine  # noqa: E402

cs_engine.Encoder = LocalEncoder  # DeepSeek 无 embedding API → 本地嵌入（零 fork）

from knowledge_storm import (  # noqa: E402
    CoStormRunner,
    CollaborativeStormLMConfigs,
    RunnerArgument,
    LoggingWrapper,
)
from knowledge_storm.lm import LitellmModel  # noqa: E402

runner = None
emitted = 0  # conversation_history 中已发出的条数
_SESS_MD = None  # 讨论实录（人读，Obsidian 可开）
_SESS_JSONL = None  # 讨论实录（机读，供解题/执行 Agent）


def _note(obj, md_chunk=None):
    """每轮发言/事件实时落盘：jsonl 机读 + md 人读，进程退出也不丢。"""
    if _SESS_JSONL:
        with open(_SESS_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    if _SESS_MD and md_chunk:
        with open(_SESS_MD, "a", encoding="utf-8") as f:
            f.write(md_chunk)


def emit_new_turns():
    global emitted
    hist = runner.conversation_history
    for t in hist[emitted:]:
        ev = {"event": "turn", "role": t.role, "type": str(t.utterance_type), "text": t.utterance}
        emit(ev)
        _note(ev, f"\n## [{t.role}]（{t.utterance_type}）\n\n{t.utterance}\n")
    emitted = len(hist)


def start(topic, background=""):
    global runner, emitted, _SESS_MD, _SESS_JSONL
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        emit({"event": "error", "msg": "未检测到 DEEPSEEK_API_KEY（_雷达/.env）"})
        return
    disc = HERE / "discussions"
    disc.mkdir(exist_ok=True)
    slug = re.sub(r'[\\/:*?"<>|\s]+', "_", topic)[:40]
    stem = f"{datetime.now():%Y%m%d_%H%M}_圆桌_{slug}"
    _SESS_MD = disc / (stem + ".md")
    _SESS_JSONL = disc / (stem + ".jsonl")
    _SESS_MD.write_text(f"# 圆桌讨论实录：{topic}\n\n> 逐轮实时落盘；整合报告另见 reports/。机读版同名 .jsonl。\n",
                        encoding="utf-8")
    _note({"event": "session", "topic": topic, "started": datetime.now().isoformat(timespec="seconds"),
           "md": _SESS_MD.name, "jsonl": _SESS_JSONL.name})
    emit({"event": "session", "md": _SESS_MD.name, "jsonl": _SESS_JSONL.name})
    lm = LitellmModel(model="deepseek/deepseek-flash", api_key=key,
                      model_type="chat", temperature=1.0, top_p=0.9,
                      extra_body={"thinking": {"type": "disabled"}})
    cfg = CollaborativeStormLMConfigs()
    for setter in ("set_question_answering_lm", "set_discourse_manage_lm",
                   "set_utterance_polishing_lm", "set_warmstart_outline_gen_lm",
                   "set_question_asking_lm", "set_knowledge_base_lm"):
        getattr(cfg, setter)(lm)
    args = RunnerArgument(
        topic=topic, retrieve_top_k=5, max_search_queries=2,
        total_conv_turn=10, max_search_thread=3,
        warmstart_max_num_experts=2, warmstart_max_turn_per_experts=1,
        max_thread_num=4,
    )
    runner = CoStormRunner(lm_config=cfg, runner_argument=args,
                           logging_wrapper=LoggingWrapper(cfg),
                           rm=DeepSeekSearchRM(k=args.retrieve_top_k))
    emit({"event": "status", "msg": "warm_start 中（专家生成+现场检索，约 1–2 分钟）…"})
    runner.warm_start()
    # 格式漂移兜底：专家输出缺分隔符时 storm 内部吞错→对话为空；空则重试（零 fork，适配器层）
    for _ in range(2):
        if runner.conversation_history:
            break
        emit({"event": "status", "msg": "warm_start 产出为空（专家格式漂移），重试中…"})
        runner.warm_start()
    emitted = 0
    emit_new_turns()
    if background:
        emit({"event": "status", "msg": "注入报告背景，专家消化中…"})
        runner.step(user_utterance=(
            "以下是已有研究报告，仅供讨论参考；不要受限于它，可现场检索补充、质疑或延伸：\n"
            + background[:4000]))
        emit_new_turns()
        runner.step()  # step(user_utterance) 只插入不回应，需再 step 才出专家回应（官方 docstring 实证）
        if len(runner.conversation_history) <= emitted:
            runner.step()  # 格式漂移兜底重试
        emit_new_turns()
    emit({"event": "ready", "msg": "圆桌就绪：可插话或让专家继续"})


def main():
    emit({"event": "status", "msg": "适配器已启动，等待 start 命令"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            emit({"event": "error", "msg": "非法 JSON 命令"})
            continue
        c = cmd.get("cmd")
        try:
            if c == "start":
                start(cmd.get("topic", "").strip(), cmd.get("background", ""))
            elif c in ("say", "next"):
                if runner is None:
                    emit({"event": "error", "msg": "圆桌未开始"})
                    continue
                text = cmd.get("text", "").strip() if c == "say" else ""
                if text:
                    runner.step(user_utterance=text)  # 只插入用户发言
                    emit_new_turns()
                emit({"event": "status", "msg": "专家检索+组织回答中…"})
                before = len(runner.conversation_history)
                runner.step()  # 专家回应（对插话或继续讨论）
                if len(runner.conversation_history) == before:
                    emit({"event": "status", "msg": "本轮无新发言（格式漂移），重试一次…"})
                    runner.step()
                emit_new_turns()
                emit({"event": "ready", "msg": "本轮完成"})
            elif c == "report":
                if runner is None:
                    emit({"event": "error", "msg": "圆桌未开始"})
                    continue
                emit({"event": "status", "msg": "整合圆桌报告中…"})
                if not runner.conversation_history:
                    emit({"event": "error", "msg": "圆桌无有效发言（warm_start 连续失败），不生成空骨架报告；可结束重开"})
                    emit({"event": "ready", "msg": "出错后恢复，可继续"})
                    continue
                report = runner.generate_report()
                # 截断兜底：总结尾句不完整（LLM 输出上限）时重试一次，取更完整者
                if report and report.rstrip()[-1:] not in "。！？.!?)）":
                    emit({"event": "status", "msg": "报告尾句截断，重试整合一次…"})
                    retry = runner.generate_report()
                    if retry and len(retry) > len(report):
                        report = retry
                # 精确来源清单：引用编号=knowledge_base.info_uuid_to_info_dict 的整数键（官方 article_generation 同款）
                refs, seen = [], set()
                kb = getattr(runner, "knowledge_base", None)
                idx_map = getattr(kb, "info_uuid_to_info_dict", {}) or {}
                for idx in sorted(idx_map.keys()):
                    url = getattr(idx_map[idx], "url", "")
                    if url and url not in seen:
                        seen.add(url)
                        refs.append(f"[{idx}]: {url}")
                ref_block = ("\n\n## 来源清单（编号与正文引用一致）\n" + "\n".join(refs)) if refs else ""
                out_dir = HERE / "reports"
                out_dir.mkdir(exist_ok=True)
                slug = re.sub(r'[\\/:*?"<>|\s]+', "_", runner.runner_argument.topic)[:40]
                path = out_dir / f"{datetime.now():%Y%m%d_%H%M}_圆桌_{slug}.md"
                path.write_text(f"# {runner.runner_argument.topic}（Co-STORM 圆桌报告）\n\n{report}{ref_block}\n",
                                encoding="utf-8")
                _note({"event": "report", "name": path.name, "refs": len(refs)},
                      f"\n---\n整合报告：[[{path.name}]]（来源 {len(refs)} 条）\n")
                emit({"event": "report", "path": str(path), "name": path.name})
            elif c == "quit":
                emit({"event": "bye"})
                break
            else:
                emit({"event": "error", "msg": f"未知命令 {c}"})
        except Exception as e:  # 单轮失败不杀会话
            emit({"event": "error", "msg": f"{type(e).__name__}: {e}"})
            emit({"event": "ready", "msg": "出错后恢复，可继续"})


if __name__ == "__main__":
    main()
