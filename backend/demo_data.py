"""访客虚构示例数据（公开安全）。

任务书红线：默认首页与访客只能看到明确标记的虚构示例，绝不暴露个人历史/报告/密钥。
本模块所有内容为编造的演示素材，与用户真实数据无关。真实数据仅在所有者登录后经
DATA_DIR 提供。
"""

DEMO_REPORT_NAME = "示例报告_虚构的校园二手书定价.md"
DEMO_DISCUSSION_NAME = "示例圆桌_虚构的二手书定价讨论.md"
DEMO_SOLUTION_NAME = "示例方案_虚构问题档案.md"
DEMO_TASKCARD_NAME = "TC-DEMO-01_虚构示例任务卡.md"
DEMO_SESSION_ID = "demo"

DEMO_REPORT_MD = """# 【示例·虚构】校园二手书定价小研究

> 这是给访客看的**虚构演示报告**，不是任何真实研究。登录后才会显示你自己的真实报告。

## 背景（虚构）
某虚构大学的同学想知道：二手教材按什么折扣挂出去最容易成交。

## 方法（虚构）
- 采集 3 个虚构平台共 120 条虚构挂牌记录。
- 按「原价折扣 × 成色」分桶，统计 7 日成交率。

## 发现（虚构）
| 折扣区间 | 成色 | 7日成交率（虚构） |
|---|---|---|
| 3–4 折 | 九成新 | 61% |
| 4–5 折 | 八成新 | 38% |
| 5 折以上 | 任意 | 12% |

## 结论（虚构）
九成新教材挂 3.5 折附近成交最快；这只是演示数字，请勿当真。

## 出处（虚构）
- https://example.com/demo-pricing （示例链接，非真实来源）
"""

DEMO_DISCUSSION_MD = """# 【示例·虚构】圆桌：二手书定价讨论

> 虚构演示实录。真实圆桌登录后才可见。

**[经济学专家]** 折扣弹性比成色更敏感，建议先锚定 3–4 折区间。（虚构发言）

**[用户插话]** 那如果书里有笔记呢？（虚构插话）

**[行为学专家]** 干净笔记可能加分，涂画严重则减分，需单独分桶。（虚构发言）

**[收敛]** 下一步：按「有无笔记」再切一刀验证。（虚构结论）
"""

DEMO_SOLUTION_MD = """# 【示例·虚构】问题档案：二手书定价

> 虚构演示方案档案。

## 当前解法（虚构）
九成新 → 3.5 折；有干净笔记 → 维持；涂画严重 → 降 0.5 折。

## 验收清单（虚构）
- [ ] 成交率 ≥ 50%
- [ ] 平均成交周期 ≤ 7 天

## 状态
示例（虚构）
"""

DEMO_TASKCARD_MD = """---
id: TC-DEMO-01
title: 虚构示例任务卡
status: 待执行
created: 2026-01-01
source: 示例报告_虚构的校园二手书定价.md
---
# TC-DEMO-01 · 虚构示例任务卡

> 这是**虚构演示任务卡**，展示任务卡长什么样。真实任务卡登录后才可见，且不会被访客领取。

## 目标（虚构）
验证「有无笔记」对成交率的影响。

## 步骤（虚构）
1. 采集带笔记/无笔记两组样本各 30 条。
2. 对比 7 日成交率。

## 验收断言（虚构）
两组成交率差异 ≥ 10 个百分点则假设成立。

## 证据指针（虚构）
示例报告_虚构的校园二手书定价.md

## 风险与授权门槛（虚构）
无（纯演示）。
"""

DEMO_MESSAGES = [
    {"id": 1, "session_id": DEMO_SESSION_ID, "ts": "2026-01-01T09:00:00+08:00",
     "role": "note", "content": "【示例】这是访客演示会话，内容为虚构。登录后进入你的真实工作区。", "label": "", "request_id": ""},
    {"id": 2, "session_id": DEMO_SESSION_ID, "ts": "2026-01-01T09:01:00+08:00",
     "role": "user", "content": "这份示例报告讲了什么？", "label": "", "request_id": ""},
    {"id": 3, "session_id": DEMO_SESSION_ID, "ts": "2026-01-01T09:01:05+08:00",
     "role": "assistant", "content": "这是一份**虚构演示**：二手教材九成新挂 3.5 折附近成交最快。数字都是编的，仅用于展示界面。登录后右栏会基于你真实在看的报告答疑。", "label": "", "request_id": ""},
]


def demo_reports():
    return [{"name": DEMO_REPORT_NAME, "mtime": "示例", "size": len(DEMO_REPORT_MD), "has_feedback": False}]


def demo_discussions():
    return [{"name": DEMO_DISCUSSION_NAME, "mtime": "示例"}]


def demo_solutions():
    return [{"name": DEMO_SOLUTION_NAME, "mtime": "示例"}]


def demo_taskcards():
    return [{"name": DEMO_TASKCARD_NAME, "status": "待执行", "mtime": "示例"}]


def demo_history_listing():
    return {"sessions": [{"id": DEMO_SESSION_ID, "title": "【示例·虚构】访客演示会话",
                          "created": "2026-01-01T09:00:00+08:00", "updated": "2026-01-01T09:01:05+08:00",
                          "count": len(DEMO_MESSAGES)}],
            "legacy_notice": "访客模式：仅显示虚构示例。登录后加载真实历史（含旧版 45 条原样保留）。"}


def demo_session(render_md):
    msgs = []
    for m in DEMO_MESSAGES:
        mm = dict(m)
        mm["html"] = render_md(m["content"]) if m["role"] == "assistant" else ""
        msgs.append(mm)
    return {"id": DEMO_SESSION_ID, "title": "【示例·虚构】访客演示会话",
            "created": "2026-01-01T09:00:00+08:00", "updated": "2026-01-01T09:01:05+08:00",
            "context": {"kind": "report", "name": DEMO_REPORT_NAME,
                        "label": "报告 " + DEMO_REPORT_NAME, "text": DEMO_REPORT_MD},
            "messages": msgs,
            "events": [{"id": 1, "session_id": DEMO_SESSION_ID, "ts": "2026-01-01T09:01:00+08:00",
                        "kind": "report", "name": DEMO_REPORT_NAME, "source": "示例"}]}


DEMO_TEXTS = {
    DEMO_REPORT_NAME: DEMO_REPORT_MD,
    DEMO_DISCUSSION_NAME: DEMO_DISCUSSION_MD,
    DEMO_SOLUTION_NAME: DEMO_SOLUTION_MD,
    DEMO_TASKCARD_NAME: DEMO_TASKCARD_MD,
}
