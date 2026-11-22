# E1 端到端运行脚本：真问题 → DeepSeek 检索 → 带出处报告 → 落 _雷达/reports/
# 用法：.\venv-gptr\Scripts\python.exe run_e1.py "你的真问题"
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from gpt_researcher import GPTResearcher  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('用法: python run_e1.py "你的真问题"')
        return
    query = sys.argv[1].strip()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("未检测到 DEEPSEEK_API_KEY：请先在 _雷达/.env 中自行填入（不要发进聊天）。")
        return
    print(f"研究问题：{query}")
    print(f"检索器：{os.environ.get('RETRIEVER')}  LLM：{os.environ.get('FAST_LLM')}")
    researcher = GPTResearcher(query=query, report_type="research_report", report_source="web")
    await researcher.conduct_research()
    report = await researcher.write_report()

    out_dir = HERE / "reports"
    out_dir.mkdir(exist_ok=True)
    slug = re.sub(r'[\\/:*?"<>|\s]+', "_", query)[:40]
    out_path = out_dir / f"{datetime.now():%Y%m%d_%H%M}_{slug}.md"
    sources = getattr(researcher, "get_source_urls", lambda: [])() or []
    source_block = "\n\n## 来源清单\n" + "\n".join(f"- {u}" for u in sources) if sources else ""
    out_path.write_text(f"# {query}\n\n{report}{source_block}\n", encoding="utf-8")
    print(f"报告已落盘：{out_path}")
    print(f"来源 {len(sources)} 条。验收：≥1 条改变决策的线索 + 出处可点。")


if __name__ == "__main__":
    asyncio.run(main())
