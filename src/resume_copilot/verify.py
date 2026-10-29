"""确定性质量闸门。

模型会自我表扬，所以「合格与否」不能交给模型自己判断。
这里用可复现的规则做三件事：
1. 数字溯源 —— 简历里出现的每个数字，必须能在事实库里找到；
2. 关键词覆盖 —— JD 的高频词是否出现在简历里；
3. 语言体检 —— 空话、形容词堆叠、要点过长。
"""

from __future__ import annotations

import re

from .schemas import bullet_stats, extract_numbers, resume_plain_text

EMPTY_PHRASES = (
    "沟通能力强",
    "抗压能力强",
    "性格开朗",
    "吃苦耐劳",
    "有责任心",
    "学习能力强",
    "踏实肯干",
    "团队协作能力强",
    "熟练掌握",
    "精通",
    "全流程负责",
    "综合能力强",
)

BLACKLIST_ROLE = ("希望能", "愿为公司", "奉献")

_DIGITS = re.compile(r"\d+")

# 带单位/百分号/加号的数字才算「指标」，需要溯源；
# "从 0 到 1""三场比赛"这类修辞性数字不该被当成业绩数据。
_METRIC_HINT = re.compile(r"[+%]|[\u4e00-\u9fa5]|star|fork|k\b|qps|ms", re.I)


def _is_metric_token(token: str) -> bool:
    digits = _DIGITS.findall(token.replace(",", "").replace("，", ""))
    if not digits:
        return False
    if _METRIC_HINT.search(token):
        return True
    return any(int(d) >= 100 for d in digits)


def _digits(text: str) -> set[str]:
    # 先把千分位与全角逗号去掉，避免 "1,500" 与 "1500" 判成两个数
    cleaned = (text or "").replace(",", "").replace("，", "")
    return {d.lstrip("0") or "0" for d in _DIGITS.findall(cleaned)}


def _facts_corpus(facts: dict) -> str:
    return "\n".join(f["text"] + " " + " ".join(f.get("numbers") or []) for f in facts.get("facts", []))


def check_card(card: dict) -> list[dict]:
    """速查卡的确定性检查：时长、问题数、口播稿是否口语到能念。"""
    issues: list[dict] = []
    intro = card.get("self_intro") or []
    chars = sum(len(b.get("text", "")) for b in intro)
    if intro:
        if chars > 700:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "intro_too_long",
                    "where": "自我介绍",
                    "problem": f"口播稿 {chars} 字，按 200 字/分约 {chars / 200:.1f} 分钟，会超时",
                    "fix": "删掉「第二证据」的铺陈与收尾修饰，保留所有数字，压到 560–660 字。",
                }
            )
        elif chars < 480:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "intro_too_short",
                    "where": "自我介绍",
                    "problem": f"口播稿仅 {chars} 字，约 {chars / 200:.1f} 分钟，撑不满 3 分钟",
                    "fix": "给主证据补一个具体场景（时间、对象、被拒绝后怎么改），不要堆形容词。",
                }
            )
    if len(card.get("questions") or []) < 5:
        issues.append(
            {
                "severity": "warn",
                "kind": "few_questions",
                "where": "高频问题",
                "problem": f"只有 {len(card.get('questions') or [])} 个问题，目标是 5 个",
                "fix": "补到 5 个，覆盖：动机、失败经历、能力证明、压力情境、地点意愿。",
            }
        )
    return issues


def _iter_bullets(resume: dict):
    for sec in resume.get("sections", []):
        for item in sec["items"]:
            if item["type"] == "role":
                for b in item.get("bullets", []):
                    yield sec["title"], item.get("org", ""), b
            elif item["type"] == "bullet":
                yield sec["title"], "", item


def check_numbers(resume: dict, facts: dict) -> list[dict]:
    corpus_digits = _digits(_facts_corpus(facts))
    issues: list[dict] = []
    for section, org, bullet in _iter_bullets(resume):
        text = f"{bullet.get('lead', '')}{bullet.get('text', '')}"
        for token in extract_numbers(text):
            if not _is_metric_token(token):
                continue
            nums = _digits(token)
            if not nums:
                continue
            if not nums <= corpus_digits:
                missing = "、".join(sorted(nums - corpus_digits))
                issues.append(
                    {
                        "severity": "error",
                        "kind": "unsourced_number",
                        "where": f"{section} · {org}".strip(" ·"),
                        "problem": f"数字「{token}」在事实库里找不到出处（{missing}）",
                        "fix": "删除或改成事实库里的真实数字；没有实测数据就不要写指标。",
                    }
                )
    return issues


def check_fact_refs(resume: dict, facts: dict) -> list[dict]:
    known = {f["id"] for f in facts.get("facts", [])}
    issues: list[dict] = []
    for section, org, bullet in _iter_bullets(resume):
        for ref in bullet.get("fact_refs") or []:
            if ref not in known:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "dangling_fact_ref",
                        "where": f"{section} · {org}".strip(" ·"),
                        "problem": f"引用了不存在的事实 {ref}",
                        "fix": "改为事实库中真实存在的 ID。",
                    }
                )
    return issues


# 客户行业词：出现在简历里就等于宣称"我有这类客户经验"，
# 事实库没提过就该报错，而不是等面试官问出来。
INDUSTRY_TERMS = (
    "政府客户", "金融客户", "教育客户", "医疗客户", "运营商客户",
    "党政", "银行客户", "医院客户", "大客户", "世界 500 强",
)


def check_entity_leak(resume: dict, facts: dict) -> list[dict]:
    corpus = _facts_corpus(facts)
    issues: list[dict] = []
    for section, org, bullet in _iter_bullets(resume):
        text = f"{bullet.get('lead', '')}{bullet.get('text', '')}"
        for term in INDUSTRY_TERMS:
            if term in text and term not in corpus:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "unsupported_entity",
                        "where": f"{section} · {org}".strip(" ·"),
                        "problem": f"出现「{term}」，但事实库里没有任何该行业客户经历",
                        "fix": "删掉行业词，改成事实支持的表述（如「商户」「客户」）。",
                    }
                )
    return issues


def check_language(resume: dict) -> list[dict]:
    issues: list[dict] = []
    for section, org, bullet in _iter_bullets(resume):
        text = f"{bullet.get('lead', '')}{bullet.get('text', '')}"
        for phrase in EMPTY_PHRASES:
            if phrase in text:
                issues.append(
                    {
                        "severity": "warn",
                        "kind": "empty_phrase",
                        "where": f"{section} · {org}".strip(" ·"),
                        "problem": f"出现空话「{phrase}」",
                        "fix": "换成可验证的事实或数字；形容词不提供信息量。",
                    }
                )
        if len(text) > 96:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "too_long",
                    "where": f"{section} · {org}".strip(" ·"),
                    "problem": f"单条要点 {len(text)} 字，超过 96 字，一页放不下也读不动",
                    "fix": "拆成两条，或删掉修饰语只留动词+对象+数字。",
                }
            )
    return issues


def keyword_coverage(resume: dict, keywords: list[str]) -> dict:
    text = resume_plain_text(resume)
    kws = [k for k in keywords if k and len(k) <= 12]
    if not kws:
        return {"ratio": 1.0, "hit": [], "miss": [], "checked": 0}
    hit = [k for k in kws if k in text]
    miss = [k for k in kws if k not in text]
    return {"ratio": round(len(hit) / len(kws), 3), "hit": hit, "miss": miss, "checked": len(kws)}


def check_structure(resume: dict) -> list[dict]:
    """结构性问题（缺姓名、空模块、role 没有内容）比措辞问题更致命。"""
    from .schemas import validate_resume

    return [
        {
            "severity": "error",
            "kind": "structure",
            "where": "结构",
            "problem": message,
            "fix": "补齐该字段；若是模型漏写，让撰写员重写这一节。",
        }
        for message in validate_resume(resume)
    ]


def check_resume(resume: dict, facts: dict, jd: dict) -> dict:
    issues: list[dict] = []
    issues += check_structure(resume)
    issues += check_numbers(resume, facts)
    issues += check_fact_refs(resume, facts)
    issues += check_entity_leak(resume, facts)
    issues += check_language(resume)
    cov = keyword_coverage(resume, jd.get("keywords") or [])
    if cov["checked"] >= 6 and cov["ratio"] < 0.35:
        issues.append(
            {
                "severity": "warn",
                "kind": "low_keyword_coverage",
                "where": "全文",
                "problem": f"JD 关键词覆盖仅 {cov['ratio']:.0%}，漏掉：{'、'.join(cov['miss'][:8])}",
                "fix": "在技能或项目里自然补上真正掌握的词，不要硬塞没做过的。",
            }
        )
    stats = bullet_stats(resume)
    errors = [i for i in issues if i["severity"] == "error"]
    warns = [i for i in issues if i["severity"] == "warn"]
    return {
        "pass": not errors,
        "issues": issues,
        "metrics": {"keyword_coverage": cov["ratio"], "keywords_miss": cov["miss"], "errors": len(errors), "warnings": len(warns), **stats},
    }


def issues_as_prompt(report: dict, limit: int = 20) -> str:
    lines = []
    for issue in report.get("issues", [])[:limit]:
        lines.append(f"- [{issue['severity']}] {issue['where']}：{issue['problem']} → {issue['fix']}")
    return "\n".join(lines) if lines else "（无问题）"
