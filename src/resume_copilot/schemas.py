"""数据结构与规范化。

模型输出不可全信，所以这里做三件事：
1) 把各种脏输入收敛成固定形状（缺字段补默认、类型错误纠正）；
2) 校验硬约束（必须有姓名、必须有 section、bullet 必须有正文）；
3) 提供 flatten 后的纯文本，供关键词覆盖率与事实校验使用。
"""

from __future__ import annotations

import re
from typing import Any

from .jsonx import as_list, as_text

ROLE_FAMILIES = ("sales", "rnd", "support", "other")

# 关键词带权重：岗位名里"实施/运维"这类信号比泛化的"工程师"更具体，
# 所以"实施工程师"应该判成 support，"技术研发工程师"判成 rnd。
ROLE_KEYWORDS: dict[str, dict[str, int]] = {
    "sales": {
        "客户经理": 3,
        "销售": 3,
        "大客户": 3,
        "渠道": 2,
        "商务": 2,
        "account": 2,
        "客户代表": 3,
    },
    "rnd": {
        "研发": 3,
        "开发": 3,
        "算法": 3,
        "后端": 3,
        "前端": 3,
        "架构": 3,
        "测试开发": 3,
        "客户端": 3,
        "工程师": 1,
    },
    "support": {
        "实施": 3,
        "运维": 3,
        "技术支持": 3,
        "售前": 3,
        "售后": 3,
        "交付": 2,
        "驻场": 3,
        "客户成功": 3,
    },
}


def guess_role_family(text: str) -> str:
    t = text or ""
    scores = {family: sum(weight for kw, weight in kws.items() if kw in t) for family, kws in ROLE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


# ---------------- JD 画像 ----------------
def normalize_jd_profile(raw: dict, role_hint: str = "") -> dict:
    title = as_text(raw.get("title")) or as_text(raw.get("job_title")) or "目标岗位"
    family = as_text(raw.get("role_family"))
    if family not in ROLE_FAMILIES:
        family = guess_role_family(f"{title} {role_hint}")
    return {
        "title": title,
        "company": as_text(raw.get("company")),
        "role_family": family,
        "seniority": as_text(raw.get("seniority"), "campus") or "campus",
        "must_have": [as_text(x) for x in as_list(raw.get("must_have")) if as_text(x)],
        "nice_to_have": [as_text(x) for x in as_list(raw.get("nice_to_have")) if as_text(x)],
        "responsibilities": [as_text(x) for x in as_list(raw.get("responsibilities")) if as_text(x)],
        "hidden_preferences": [as_text(x) for x in as_list(raw.get("hidden_preferences")) if as_text(x)],
        "keywords": [as_text(x) for x in as_list(raw.get("keywords")) if as_text(x)],
        "screening_logic": as_text(raw.get("screening_logic")),
        "risks": [as_text(x) for x in as_list(raw.get("risks")) if as_text(x)],
    }


# ---------------- 事实库 ----------------
def normalize_facts(raw: dict) -> dict:
    facts: list[dict] = []
    for i, item in enumerate(as_list(raw.get("facts")), 1):
        if not isinstance(item, dict):
            item = {"text": as_text(item)}
        text = as_text(item.get("text"))
        if not text:
            continue
        facts.append(
            {
                "id": as_text(item.get("id")) or f"F{i}",
                "category": as_text(item.get("category"), "experience"),
                "text": text,
                "numbers": [as_text(n) for n in as_list(item.get("numbers")) if as_text(n)],
                "source": as_text(item.get("source")),
                "confidence": as_text(item.get("confidence"), "high"),
                "transferable": as_text(item.get("transferable")),
            }
        )
    return {"facts": facts}


def facts_as_prompt(facts: dict, limit: int = 200) -> str:
    lines = []
    for fact in facts.get("facts", [])[:limit]:
        nums = f" 数字={fact['numbers']}" if fact.get("numbers") else ""
        lines.append(f"[{fact['id']}] ({fact['category']}) {fact['text']}{nums}  来源：{fact.get('source') or '-'}")
    return "\n".join(lines)


# ---------------- 定位策略 ----------------
def normalize_positioning(raw: dict) -> dict:
    return {
        "headline": as_text(raw.get("headline")),
        "narrative": as_text(raw.get("narrative")),
        "differentiators": [as_text(x) for x in as_list(raw.get("differentiators")) if as_text(x)],
        "highlight_fact_ids": [as_text(x) for x in as_list(raw.get("highlight_fact_ids")) if as_text(x)],
        "omit": [as_text(x) for x in as_list(raw.get("omit")) if as_text(x)],
        "risk_plan": [as_text(x) for x in as_list(raw.get("risk_plan")) if as_text(x)],
    }


# ---------------- 简历结构 ----------------
def _normalize_bullets(raw: Any) -> list[dict]:
    out: list[dict] = []
    for item in as_list(raw):
        if isinstance(item, str):
            lead, _, text = item.partition("：") if "：" in item else ("", "", item)
            out.append({"lead": lead.strip(), "text": text.strip(), "fact_refs": []})
            continue
        if not isinstance(item, dict):
            continue
        text = as_text(item.get("text"))
        if not text:
            continue
        out.append(
            {
                "lead": as_text(item.get("lead")),
                "text": text,
                "fact_refs": [as_text(x) for x in as_list(item.get("fact_refs")) if as_text(x)],
            }
        )
    return out


def normalize_resume(raw: dict) -> dict:
    header_raw = raw.get("header") or {}
    objective = header_raw.get("objective") or {}
    if isinstance(objective, str):
        objective = {"role": objective}
    header = {
        "name": as_text(header_raw.get("name")),
        "name_en": as_text(header_raw.get("name_en")),
        "objective": {
            "role": as_text(objective.get("role")),
            "detail": as_text(objective.get("detail")),
            "meta": as_text(objective.get("meta")),
        },
        "contacts": [as_text(x) for x in as_list(header_raw.get("contacts")) if as_text(x)],
        "meta": [as_text(x) for x in as_list(header_raw.get("meta")) if as_text(x)],
    }

    sections: list[dict] = []
    for i, sec in enumerate(as_list(raw.get("sections")), 1):
        if not isinstance(sec, dict):
            continue
        items: list[dict] = []
        for item in as_list(sec.get("items")):
            if not isinstance(item, dict):
                continue
            kind = as_text(item.get("type"), "bullet") or "bullet"
            if kind == "role":
                org = as_text(item.get("org"))
                if not org:
                    continue
                items.append(
                    {
                        "type": "role",
                        "org": org,
                        "role": as_text(item.get("role")),
                        "date": as_text(item.get("date")),
                        "stack": as_text(item.get("stack")),
                        "sub": as_text(item.get("sub")),
                        "bullets": _normalize_bullets(item.get("bullets")),
                    }
                )
            elif kind == "text":
                text = as_text(item.get("text"))
                if text:
                    items.append({"type": "text", "text": text})
            else:
                bullets = _normalize_bullets([item])
                for b in bullets:
                    items.append({"type": "bullet", **b})
        title = as_text(sec.get("title"))
        if not title or not items:
            continue
        sections.append(
            {
                "id": as_text(sec.get("id")) or f"S{i}",
                "title": title,
                "en": as_text(sec.get("en")),
                "items": items,
            }
        )

    return {"header": header, "sections": sections}


def validate_resume(resume: dict) -> list[str]:
    errors: list[str] = []
    header = resume.get("header") or {}
    if not header.get("name"):
        errors.append("header.name 为空：简历必须有姓名")
    if not (header.get("objective") or {}).get("role"):
        errors.append("header.objective.role 为空：必须有求职意向")
    if not header.get("contacts"):
        errors.append("header.contacts 为空：至少要有电话或邮箱")
    sections = resume.get("sections") or []
    if not sections:
        errors.append("sections 为空：至少要有一个模块")
    bullets = [b for s in sections for i in s["items"] if i["type"] in ("role", "bullet") for b in ([*i.get("bullets", [])] if i["type"] == "role" else [i])]
    if len(bullets) > 34:
        errors.append(f"要点过多（{len(bullets)} 条），一页放不下，建议压到 30 条以内")
    for s in sections:
        for i in s["items"]:
            if i["type"] == "role" and not i.get("bullets") and not i.get("sub"):
                errors.append(f"{s['title']} · {i['org']}：既没有要点也没有说明行")
    return errors


def resume_plain_text(resume: dict) -> str:
    header = resume.get("header") or {}
    parts = [
        header.get("name", ""),
        (header.get("objective") or {}).get("role", ""),
        (header.get("objective") or {}).get("detail", ""),
        " ".join(header.get("contacts", [])),
        " ".join(header.get("meta", [])),
    ]
    for sec in resume.get("sections", []):
        parts.append(sec["title"])
        for item in sec["items"]:
            if item["type"] == "role":
                parts.extend([item.get("org", ""), item.get("role", ""), item.get("stack", ""), item.get("sub", "")])
                parts.extend(f"{b['lead']}{b['text']}" for b in item.get("bullets", []))
            elif item["type"] == "bullet":
                parts.append(f"{item['lead']}{item['text']}")
            else:
                parts.append(item.get("text", ""))
    return "\n".join(p for p in parts if p)


def bullet_stats(resume: dict) -> dict:
    sections = resume.get("sections", [])
    roles = bullets = 0
    chars = 0
    for sec in sections:
        for item in sec["items"]:
            if item["type"] == "role":
                roles += 1
                bullets += len(item.get("bullets", []))
                chars += sum(len(b["text"]) for b in item.get("bullets", []))
            elif item["type"] == "bullet":
                bullets += 1
                chars += len(item["text"])
    return {"sections": len(sections), "roles": roles, "bullets": bullets, "chars": chars}


# ---------------- 面试速查卡 ----------------
def normalize_card(raw: dict) -> dict:
    intro = []
    for block in as_list(raw.get("self_intro")):
        if not isinstance(block, dict):
            continue
        intro.append(
            {
                "time": as_text(block.get("time")),
                "label": as_text(block.get("label")),
                "text": as_text(block.get("text")),
            }
        )
    qa = []
    for item in as_list(raw.get("questions")):
        if not isinstance(item, dict):
            continue
        qa.append(
            {
                "q": as_text(item.get("q")),
                "skeleton": as_text(item.get("skeleton")),
                "evidence": as_text(item.get("evidence")),
            }
        )
    return {
        "process": [as_text(x) for x in as_list(raw.get("process")) if as_text(x)],
        "self_intro": intro,
        "self_intro_note": as_text(raw.get("self_intro_note")),
        "questions": qa,
        "group_or_technical": {
            "title": as_text((raw.get("group_or_technical") or {}).get("title")),
            "steps": [as_text(x) for x in as_list((raw.get("group_or_technical") or {}).get("steps")) if as_text(x)],
            "tactics": [as_text(x) for x in as_list((raw.get("group_or_technical") or {}).get("tactics")) if as_text(x)],
        },
        "checklist": [as_text(x) for x in as_list(raw.get("checklist")) if as_text(x)],
        "questions_to_ask": [as_text(x) for x in as_list(raw.get("questions_to_ask")) if as_text(x)],
    }


def card_to_markdown(card: dict, title: str = "面试速查卡") -> str:
    lines = [f"# {title}", ""]
    if card.get("process"):
        lines += ["## 流程", ""]
        lines += [f"{i}. {x}" for i, x in enumerate(card["process"], 1)]
        lines += [""]
    if card.get("self_intro"):
        lines += ["## 自我介绍（分段时间块）", ""]
        for b in card["self_intro"]:
            lines += [f"**[{b['time']}] {b['label']}**", "", b["text"], ""]
        if card.get("self_intro_note"):
            lines += [f"> {card['self_intro_note']}", ""]
    if card.get("questions"):
        lines += ["## 高频问题", ""]
        for i, q in enumerate(card["questions"], 1):
            lines += [f"### {i}. {q['q']}", "", f"- 应答骨架：{q['skeleton']}"]
            if q.get("evidence"):
                lines.append(f"- 可引用的数字：{q['evidence']}")
            lines.append("")
    gt = card.get("group_or_technical") or {}
    if gt.get("steps") or gt.get("tactics"):
        lines += [f"## {gt.get('title') or '群面 / 技术追问'}", ""]
        lines += [f"{i}. {x}" for i, x in enumerate(gt.get("steps", []), 1)]
        if gt.get("tactics"):
            lines += ["", "**技巧**", ""] + [f"- {x}" for x in gt["tactics"]]
        lines += [""]
    if card.get("checklist"):
        lines += ["## 上场前清单", ""] + [f"- [ ] {x}" for x in card["checklist"]] + [""]
    if card.get("questions_to_ask"):
        lines += ["## 反问", ""] + [f"- {x}" for x in card["questions_to_ask"]] + [""]
    return "\n".join(lines).strip() + "\n"


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|万\+?|k\+?|星|个|家|通|条|次|元|人|天|小时|分钟)?", re.I)


def extract_numbers(text: str) -> list[str]:
    """抽出文本里的数字片段，用于「数字是否有出处」的校验。"""
    out: list[str] = []
    for m in _NUM_RE.finditer(text or ""):
        token = m.group(0).strip()
        if token and token not in out:
            out.append(token)
    return out
