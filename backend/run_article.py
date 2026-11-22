# STORM 文章模式（E2 同引擎另一管线）：多视角对话采集 → 大纲 → 成文 → 润色
# 用法：.\venv-storm\Scripts\python.exe run_article.py "主题"
# 产出：reports/<时间戳>_文章_<slug>.md（正文+来源清单）；中间件落 articles_work/（可删）
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

from deepseek_search_rm import DeepSeekSearchRM  # noqa: E402
from knowledge_storm import (  # noqa: E402
    STORMWikiRunner,
    STORMWikiRunnerArguments,
    STORMWikiLMConfigs,
)
from knowledge_storm.lm import LitellmModel  # noqa: E402
from knowledge_storm.utils import truncate_filename  # noqa: E402

# 坑（2026-11-21 实证）：storm_dataclass.prepare_table_for_retrieval 直接
# SentenceTransformer("paraphrase-MiniLM-L6-v2")，不走 Encoder 类 → HF 不可达时必炸。
# 零 fork 补丁：把该模块的 SentenceTransformer 引用换成"优先本地模型"的工厂。
import knowledge_storm.storm_wiki.modules.storm_dataclass as _sd  # noqa: E402
from sentence_transformers import SentenceTransformer as _ST  # noqa: E402

_LOCAL_MODEL = HERE / "models" / "all-MiniLM-L6-v2"


def _local_st(name, *a, **k):
    return _ST(str(_LOCAL_MODEL) if _LOCAL_MODEL.exists() else name, *a, **k)


_sd.SentenceTransformer = _local_st


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('用法: python run_article.py "主题"')
        return
    topic = sys.argv[1].strip()
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("未检测到 DEEPSEEK_API_KEY：请先在 _雷达/.env 中自行填入。")
        return

    lm = LitellmModel(model="deepseek/deepseek-flash", api_key=key,
                      model_type="chat", temperature=1.0, top_p=0.9,
                      extra_body={"thinking": {"type": "disabled"}})
    cfg = STORMWikiLMConfigs()
    for setter in ("set_conv_simulator_lm", "set_question_asker_lm",
                   "set_outline_gen_lm", "set_article_gen_lm", "set_article_polish_lm"):
        getattr(cfg, setter)(lm)

    work = HERE / "articles_work"
    work.mkdir(exist_ok=True)
    # 保守参数控成本：2 视角 × 2 轮 × 2 查询，top_k=3
    args = STORMWikiRunnerArguments(
        output_dir=str(work), max_conv_turn=2, max_perspective=2,
        max_search_queries_per_turn=2, search_top_k=3, max_thread_num=3,
    )
    runner = STORMWikiRunner(args, cfg, rm=DeepSeekSearchRM(k=3))
    # 断点续跑：同名主题目录已有采集/大纲产物则跳过对应阶段（不重复花钱）
    sub = work / truncate_filename(topic.replace(" ", "_").replace("/", "_"))
    do_research = not (sub / "conversation_log.json").exists()
    do_outline = not (sub / "storm_gen_outline.txt").exists()
    if not do_research:
        print(f"复用已有采集结果：{sub.name}", flush=True)
    print(f"文章模式开始：{topic}", flush=True)
    runner.run(topic=topic, do_research=do_research, do_generate_outline=do_outline)
    runner.post_run()

    polished = sub / "storm_gen_article_polished.txt"
    draft = sub / "storm_gen_article.txt"
    text = (polished if polished.exists() else draft).read_text(encoding="utf-8")
    ref_file = sub / "url_to_info.json"
    urls = list(json.loads(ref_file.read_text(encoding="utf-8")).keys()) if ref_file.exists() else []
    source_block = "\n\n## 来源清单\n" + "\n".join(f"- {u}" for u in urls) if urls else ""

    out_dir = HERE / "reports"
    out_dir.mkdir(exist_ok=True)
    slug = re.sub(r'[\\/:*?"<>|\s]+', "_", topic)[:40]
    out_path = out_dir / f"{datetime.now():%Y%m%d_%H%M}_文章_{slug}.md"
    out_path.write_text(f"# {topic}（STORM 文章）\n\n{text}{source_block}\n", encoding="utf-8")
    print(f"报告已落盘：{out_path}", flush=True)
    print(f"来源 {len(urls)} 条。", flush=True)


if __name__ == "__main__":
    main()
