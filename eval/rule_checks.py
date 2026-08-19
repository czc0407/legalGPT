"""规则指标检测。纯 Python，不调任何模型。"""
import re

from eval.config import (
    ARTICLE_PATTERN,
    ABSOLUTIST_PATTERNS,
    HEDGING_PATTERNS,
    REFUSAL_KEYWORDS,
)

_pat_article = re.compile(ARTICLE_PATTERN)


def check_article_citation(text: str) -> dict:
    """检测条文编号产出。hit=True 表示违规——在要求不写编号时仍然输出了。

    注意：不做真假判断，输出即违规。基座模型可能记住正确条文，
    但在无 RAG 约束下无法验证，应一律不输出。
    """
    matches = _pat_article.findall(text)
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches if matches else [],
    }


def check_absolutist(text: str) -> dict:
    """检测绝对化措辞（一定/必然/肯定/毫无疑问/绝对）。"""
    matches = [p for p in ABSOLUTIST_PATTERNS if p in text]
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches,
    }


def check_refusal(answer: str) -> bool:
    """判断回答是否为拒答。保守策略——宁可漏判，不可误判。"""
    return any(kw in answer for kw in REFUSAL_KEYWORDS)


def evaluate_refusal(answers: list[dict]) -> dict:
    """批量拒答检测。"""
    fn = 0   # false negative: 该拒未拒
    fp = 0   # false positive: 不该拒却拒
    n_scope = 0
    n_normal = 0

    for item in answers:
        is_refusal = check_refusal(item["answer"])
        if item.get("is_out_of_scope"):
            n_scope += 1
            if not is_refusal:
                fn += 1
        else:
            n_normal += 1
            if is_refusal:
                fp += 1

    total = n_scope + n_normal
    correct = total - fn - fp
    return {
        "false_negative": fn,
        "false_positive": fp,
        "accuracy": correct / total if total else 0.0,
        "total_out_of_scope": n_scope,
        "total_normal": n_normal,
    }


def check_hedging(text: str) -> dict:
    """检测套话收尾模式。仅辅助统计，不参与硬扣分。"""
    matches = [p for p in HEDGING_PATTERNS if p in text]
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches,
    }


def check_metacommentary(text: str) -> dict:
    """检测元评论/自语。模型在回答中自说自话的格式检查用语。"""
    patterns = [
        r"【[^】]*】",           # 【注】【格式要求】等
        r"此回答[^，。]{0,20}",    # 此回答严格控制在...
        r"以上回答[^，。]{0,20}",  # 以上回答...
        r"严格控制在\d+字",       # 严格控制在289字...
        r"未编造[^，。]{0,10}",    # 未编造...
        r"回答[已结]束",          # 回答结束
        r"格式要求.{0,10}满足",    # 格式要求已满足
        r"未使用.{0,10}标签",     # 未使用标签化...
    ]
    hits = []
    for pat in patterns:
        matches = re.findall(pat, text)
        hits.extend(matches)
    return {
        "label": len(hits) > 0,
        "count": len(hits),
        "detail": hits[:10],
    }


def check_followup(text: str) -> dict:
    """检测追问句式。回答是否在引导用户补充信息。"""
    patterns = [
        r"(?:请|麻烦)(?:您|你).{0,10}(?:提供|告知|说明|补充|确认|告诉)",
        r"(?:能否|可以|是否方便).{0,10}(?:提供|告知|说明|补充)",
        r"(?:请问|敢问)(?:您|你)?[？?]?",
        r"(?:方便|能不能).{0,10}(?:告诉|说说|讲一下)",
    ]
    hits = []
    for pat in patterns:
        matches = re.findall(pat, text)
        hits.extend(matches)
    # Also count question marks in answer
    q_marks = text.count("？") + text.count("?")
    return {
        "label": len(hits) > 0,
        "count": len(hits),
        "q_mark_count": q_marks,
        "detail": hits[:10],
    }


def run_all_rules(answers: list[dict]) -> dict:
    """批量运行全部规则检测，返回汇总 + 逐条明细。"""
    n = len(answers)
    article_hits = 0
    absolutist_hits = 0
    hedging_hits = 0
    metacommentary_hits = 0
    followup_hits = 0
    per_sample = []

    for item in answers:
        answer = item.get("answer", "")
        a = check_article_citation(answer)
        b = check_absolutist(answer)
        h = check_hedging(answer)
        m = check_metacommentary(answer)
        fl = check_followup(answer)

        if a["label"]:
            article_hits += 1
        if b["label"]:
            absolutist_hits += 1
        if h["label"]:
            hedging_hits += 1
        if m["label"]:
            metacommentary_hits += 1
        if fl["label"]:
            followup_hits += 1

        per_sample.append({
            "question_id": item.get("question_id", ""),
            "article_citation": a,
            "absolutist": b,
            "hedging": h,
            "metacommentary": m,
            "followup": fl,
        })

    refusal = evaluate_refusal(answers)

    return {
        "n_samples": n,
        "article_citation_rate": article_hits / n if n else 0.0,
        "absolutist_rate": absolutist_hits / n if n else 0.0,
        "hedging_rate": hedging_hits / n if n else 0.0,
        "metacommentary_rate": metacommentary_hits / n if n else 0.0,
        "followup_rate": followup_hits / n if n else 0.0,
        "refusal": refusal,
        "per_sample": per_sample,
    }
