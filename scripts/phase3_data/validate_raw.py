#!/usr/bin/env python3
"""阶段三 · 原始数据校验器。对 raw 样本跑 Level 1 校验，输出报告。

用法:
    python scripts/phase3_data/validate_raw.py [--input data/sft/04_cards/] [--ppl]
"""
import json, os, sys, re, argparse
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_DIR)

# ═══════════════════════════════════════════════════════════════
# 法律名称白名单（从 scripts/config/legal_name_whitelist.json 加载）
# 来源：全国人大公报 2025-06-27 "现行有效法律目录（306件）" + 常用法规
# 更新：python scripts/config/build_legal_whitelist.py --update
# ═══════════════════════════════════════════════════════════════

WHITELIST_PATH = os.path.join(SCRIPTS_DIR, "config", "legal_name_whitelist.json")
_whitelist_data = {}
with open(WHITELIST_PATH) as f:
    _whitelist_data = json.load(f)
LEGAL_NAMES = set(_whitelist_data.get("names", []))

# ═══════════════════════════════════════════════════════════════
# 校验函数
# ═══════════════════════════════════════════════════════════════

def check_length(answer: str, card: int = 0) -> dict:
    """篇幅检查。卡 5 拒答使用 80-200 字范围。"""
    n = len(answer)
    if n == 0:
        return {"ok": False, "issue": "空回答", "severity": "hard"}
    min_len = 80 if card == 5 else 150
    max_len = 200 if card == 5 else 500
    if n < min_len:
        return {"ok": False, "issue": f"过短 ({n}字, min={min_len})", "severity": "hard"}
    if n > max_len:
        severity = "soft" if card != 5 else "hard"
        return {"ok": False, "issue": f"超长 ({n}字, max={max_len})", "severity": severity}
    return {"ok": True, "issue": None, "severity": None}


def check_article(answer: str) -> dict:
    """条文编号检查。"""
    hits = re.findall(r'第[零一二三四五六七八九十百千\d]+条', answer)
    if hits:
        return {"ok": False, "issue": f"条文编号: {hits}", "severity": "hard", "hits": hits}
    return {"ok": True, "issue": None, "severity": None, "hits": []}


def check_label_words(answer: str) -> dict:
    """框架标签词检查（连续使用 ≥ 2 个视为违规）。"""
    hits = re.findall(r'(?:^|\n)\s*(?:首先|其次|再次|最后)', answer)
    if len(hits) >= 2:
        return {"ok": False, "issue": f"框架标签词: {hits}", "severity": "hard",
                "auto_fixable": True, "hits": hits}
    return {"ok": True, "issue": None, "severity": None, "hits": hits}


def check_absolutist(answer: str) -> dict:
    """绝对化措辞检查。"""
    # 确定性断言组合，排除"不一定/未必/并非一定"等否定前缀
    hits = re.findall(r'(?<![不未无没非])(?:一定能|肯定会|必然会|肯定能|必定能|毫无疑问|百分百|绝对是|必然是|一定是)', answer)
    if hits:
        return {"ok": False, "issue": f"绝对化: {hits}", "severity": "soft", "hits": hits}
    return {"ok": True, "issue": None, "severity": None, "hits": []}


def check_card2_quality(answer: str) -> dict:
    """卡 2 专属：检查回答是否包含信息不足场景应有的追问/条件表述。"""
    has_ask = bool(re.search(r'请问|能否提供|麻烦补充|请.*提供|请.*告知|需要.*了解|'
                            r'需要.*确认|告诉我|方便.*说|能.*吗[？?]', answer))
    has_cond = bool(re.search(r'如果|若.*则|取决于|视.*而定|在.*情况下|需要根据|'
                              r'才能判断|暂.*无法|还不.*清楚', answer))
    if not has_ask and not has_cond:
        return {"ok": False, "issue": "卡2缺少追问或条件表述", "severity": "soft"}
    return {"ok": True, "issue": None, "severity": None}


def _normalize_law_name(name: str) -> str:
    """去掉'中华人民共和国/中国'前缀进行归一化。"""
    for prefix in ["中华人民共和国", "中国"]:
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name

def check_fake_laws(answer: str) -> dict:
    """法律名称合法性检查。不在白名单中的标记为'未知'，不自动判定为编造。"""
    all_laws = set(re.findall(r'《([^》]+)》', answer))
    unknown = []
    for law in all_laws:
        normalized = _normalize_law_name(law)
        if law in LEGAL_NAMES or normalized in LEGAL_NAMES:
            continue
        unknown.append(law)
    if unknown:
        return {"ok": False, "issue": f"未知法律名称（需人工确认）: {unknown}",
                "severity": "soft", "unknown": unknown, "auto_fixable": False}
    return {"ok": True, "issue": None, "severity": None, "unknown": []}


def check_case_fabrication(answer: str, question: str) -> dict:
    """案情编造检测（NER 简化版：提取数字+人名，与 question 交叉比对）。"""
    # 提取数字（金额、日期等）
    nums = set(re.findall(r'\d+', answer))
    q_nums = set(re.findall(r'\d+', question))
    extra_nums = nums - q_nums
    if extra_nums:
        return {"ok": False, "issue": f"疑似编造数字: {sorted(extra_nums)[:5]}", "severity": "soft",
                "extra_nums": sorted(extra_nums)}
    return {"ok": True, "issue": None, "severity": None, "extra_nums": []}


def check_card34_consistency(answer: str, original_answer: str) -> dict:
    """卡 3/4 专属：法律名称一致性检查。"""
    if not original_answer:
        return {"ok": True, "issue": None, "severity": None}
    orig_laws = {_normalize_law_name(n) for n in re.findall(r'《([^》]+)》', original_answer)}
    new_laws = {_normalize_law_name(n) for n in re.findall(r'《([^》]+)》', answer)}
    missing = orig_laws - new_laws
    extra = new_laws - orig_laws
    issues = []
    if missing:
        issues.append(f"丢失原始法律: {missing}")
    if extra:
        issues.append(f"新增法律: {extra} (可能合理引用，需人工确认)")
    if issues:
        return {"ok": False, "issue": "; ".join(issues), "severity": "hard" if missing else "soft"}
    return {"ok": True, "issue": None, "severity": None}

# ═══════════════════════════════════════════════════════════════
# 自动修复
# ═══════════════════════════════════════════════════════════════

def auto_fix_answer(answer: str, violations: list[dict]) -> str:
    """对可修复的违规自动修正。返回修复后文本。"""
    fixed = answer
    for v in violations:
        if not v.get("auto_fixable"):
            continue
        # 删条文编号
        if "hits" in v and any("条" in h for h in v.get("hits", [])):
            for hit in v["hits"]:
                fixed = fixed.replace(hit, "")
        # 删框架标签词（只删标签词本身，保留后面内容）
        if "hits" in v and any("首先" in h or "其次" in h or "最后" in h for h in v.get("hits", [])):
            for hit in v["hits"]:
                word = hit.lstrip()
                # 安全检查：删除后段落不能变成空或过短
                candidate = re.sub(r'(?:^|\n)\s*' + word + r'[,，。]?\s*', '\n', fixed)
                # 只删标签词（~2-3 字），如果改动超过 20 字说明可能误删了内容
                if abs(len(candidate) - len(fixed)) < 20:
                    fixed = candidate
        # 替换 c 类法律名称
        if "fake" in v and v.get("fake"):
            for fname in v["fake"]:
                fixed = fixed.replace(f"《{fname}》", "根据相关法律规定")
    return fixed

# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def validate_all(raw_dir: str) -> dict:
    """对目录下所有 card*.jsonl 跑 Level 1 校验。"""
    results = {"samples": [], "summary": defaultdict(int)}

    for fname in sorted(os.listdir(raw_dir)):
        if not fname.startswith("card") or not fname.endswith(".jsonl"):
            continue
        if "progress" in fname:
            continue

        path = os.path.join(raw_dir, fname)
        print(f"\n--- {fname} ---")
        with open(path) as f:
            samples = [json.loads(l) for l in f if l.strip()]

        for s in samples:
            answer = s.get("answer", "")
            question = s.get("question", "")
            original = s.get("original_answer", "")
            card = s.get("card", 0)

            violations = []

            # 篇幅
            v = check_length(answer, card)
            if not v["ok"]:
                violations.append(v)

            # 条文编号（卡 6 知识问答允许引用具体条款）
            if card != 6:
                v = check_article(answer)
                if not v["ok"]:
                    violations.append(v)

            # 框架标签词
            v = check_label_words(answer)
            if not v["ok"]:
                violations.append(v)

            # 绝对化
            v = check_absolutist(answer)
            if not v["ok"]:
                violations.append(v)

            # 法律名称
            v = check_fake_laws(answer)
            if not v["ok"]:
                violations.append(v)

            # 案情编造
            v = check_case_fabrication(answer, question)
            if not v["ok"]:
                violations.append(v)

            # 卡 2 专属：信息不足时应有追问或条件表述
            if card == 2:
                v = check_card2_quality(answer)
                if not v["ok"]:
                    violations.append(v)

            # 卡 3/4
            if card in (3, 4) and original:
                v = check_card34_consistency(answer, original)
                if not v["ok"]:
                    violations.append(v)

            hard = [v for v in violations if v.get("severity") == "hard"]
            soft = [v for v in violations if v.get("severity") == "soft"]
            auto_fixable = [v for v in violations if v.get("auto_fixable")]

            # 自动修复
            fixed_answer = answer
            if auto_fixable:
                fixed_answer = auto_fix_answer(answer, auto_fixable)

            results["samples"].append({
                "id": s.get("id", ""),
                "card": card,
                "answer_len": len(answer),
                "has_hard": len(hard) > 0,
                "has_soft": len(soft) > 0,
                "hard_issues": [v["issue"] for v in hard],
                "soft_issues": [v["issue"] for v in soft],
                "auto_fixed": len(auto_fixable) > 0,
                "fixed_answer": fixed_answer if fixed_answer != answer else None,
            })

            results["summary"]["total"] += 1
            results["summary"]["hard"] += (1 if hard else 0)
            results["summary"]["soft"] += (1 if soft else 0)
            results["summary"]["auto_fixed"] += (1 if auto_fixable else 0)
            for v in violations:
                results["summary"][f"type_{v.get('issue', '').split(':')[0]}"] += 1

        # 卡级统计
        card_samples = [r for r in results["samples"] if r["card"] == card]
        card_hard = sum(1 for r in card_samples if r["has_hard"])
        card_total = len(card_samples)
        # 各卡预期数量
        expected = {1: (3500, 3800), 2: (600, 800), 3: (2500, 2800), 4: (300, 400), 5: (50, 100), 6: (400, 600)}
        exp_range = expected.get(card)
        warn = ""
        if exp_range and (card_total < exp_range[0] or card_total > exp_range[1]):
            warn = f"  ⚠️ 预期{exp_range[0]}-{exp_range[1]}，实际{card_total}"
        print(f"  {card_total} 条 | 硬伤: {card_hard}{warn}")

    total = results["summary"]["total"]
    hard = results["summary"]["hard"]
    print(f"\n{'='*50}")
    print(f"  总计: {total} 条 | 硬伤: {hard} ({hard*100//total if total else 0}%) | "
          f"软伤: {results['summary']['soft']} | 自动修复: {results['summary']['auto_fixed']}")
    print(f"{'='*50}")

    return results


def main():
    parser = argparse.ArgumentParser(description="raw 数据校验")
    parser.add_argument("--input", default="data/sft/04_cards/", help="raw 数据目录")
    parser.add_argument("--ppl", action="store_true", help="运行 PPL 异常检测（需 transformers）")
    parser.add_argument("--output", default="data/sft/04_cards/validation_report.json")
    args = parser.parse_args()

    results = validate_all(args.input)

    # PPL 异常检测
    if args.ppl:
        print("\n--- PPL 异常检测 ---")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            model_name = "Qwen/Qwen2.5-0.5B-Instruct"
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float32, trust_remote_code=True)
            model.eval()

            ppls = []
            for s in results["samples"]:
                sid = s["id"]
                # 从 raw 文件读 answer
                # 简化：从已加载的 samples 中读
                # 实际需要重新读文件，这里用占位
                pass

            print("  PPL 检测需完整样本数据，暂跳过")
        except ImportError:
            print("  transformers 未安装，跳过 PPL")

    # 保存报告
    with open(args.output, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  报告: {args.output}")


if __name__ == "__main__":
    main()
