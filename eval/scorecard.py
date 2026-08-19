#!/usr/bin/env python3
"""生成评测分数卡。从 Judge + Rules 输出汇总 M0/M1/M2 对比。

用法:
    python eval/scorecard.py --run sft --layer1 results/M0_knowledge.json
    python eval/scorecard.py --run baseline --layer1 results/M0_knowledge.json

约定:
    - Judge 输出: eval/outputs/{run}_checklist_disc.jsonl 等
    - 规则检测: 自动跑 run_all_rules
    - Layer 1: 手动传路径（不同 run 可能共用同一份知识评测）
"""
import json, sys, argparse
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_DIR / "eval" / "outputs"


def load(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def build(run: str, layer1_path: str = None) -> dict:
    sc = {"run": run}

    # ── Layer 1 ──
    if layer1_path:
        with open(layer1_path) as f:
            l1 = json.load(f)
        sc["layer1"] = {"accuracy_pct": round(l1["accuracy"], 1), "by_source": l1["by_source"]}

    # ── Panel B: Checklist ──
    for label, path in [("checklist_disc", f"{run}_checklist_disc.jsonl"),
                         ("checklist_concept", f"{run}_checklist_concept.jsonl")]:
        p = OUTPUTS_DIR / path
        if not p.exists():
            sc[label] = None
            continue
        data = load(p)
        dims = {}
        for r in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            sat = sum(1 for d in data if d["judgments"].get(r, {}).get("verdict") == "satisfied")
            dims[r] = round(sat / len(data) * 100, 1)
        acc = round(sum(dims[r] for r in ["R1", "R2", "R3", "R4"]) / 4, 1)
        comp = round(sum(dims[r] for r in ["R5", "R6"]) / 2, 1)
        sc[label] = {"n": len(data), "accuracy_pct": acc, "completeness_pct": comp, "dimensions": dims}

    # ── Panel C: Quality ──
    p = OUTPUTS_DIR / f"{run}_quality.jsonl"
    if p.exists():
        data = load(p)
        c = [d["clarity"]["score"] for d in data]
        a = [d["actionability"]["score"] for d in data if d["actionability"]["score"] is not None]
        sc["quality"] = {"n": len(data), "clarity_mean": round(sum(c) / len(c), 2),
                         "actionability_mean": round(sum(a) / len(a), 2)}

    # ── Panel D: Prudence + Refusal ──
    for label, key in [("prudence", "prudence"), ("refusal", "refusal")]:
        p = OUTPUTS_DIR / f"{run}_{key}.jsonl"
        if p.exists():
            data = load(p)
            scores = [d[key]["score"] for d in data]
            sc[label] = {"n": len(data), "mean": round(sum(scores) / len(scores), 2),
                         "dist": {"0": scores.count(0), "1": scores.count(1), "2": scores.count(2), "3": scores.count(3)}}

    # ── Panel A: Rules ──
    sys.path.insert(0, str(PROJECT_DIR))
    from eval.rule_checks import run_all_rules
    disc_file = OUTPUTS_DIR / f"{run}_disc.jsonl"
    if not disc_file.exists():
        disc_file = OUTPUTS_DIR / f"{run}_disc_v5.jsonl"  # fallback for baseline
    if disc_file.exists():
        answers = load(disc_file)
        rules = run_all_rules(answers)
        sc["rules"] = {"n": rules["n_samples"],
                       "article_pct": round(rules["article_citation_rate"] * 100, 1),
                       "absolutist_pct": round(rules["absolutist_rate"] * 100, 1),
                       "meta_pct": round(rules["metacommentary_rate"] * 100, 1),
                       "followup_pct": round(rules["followup_rate"] * 100, 1),
                       "refusal_accuracy": round(rules["refusal"]["accuracy"] * 100, 1)}

    return sc


def print_card(sc: dict):
    print(f"\n{'='*60}")
    print(f"  {sc['run']}")
    print(f"{'='*60}")

    if "layer1" in sc:
        print(f"\n  Layer 1 知识: {sc['layer1']['accuracy_pct']}%")

    # Checklist
    for k in ["checklist_disc", "checklist_concept"]:
        v = sc.get(k)
        if not v: continue
        print(f"\n  {k}:")
        print(f"    准确性: {v['accuracy_pct']}%  完整性: {v['completeness_pct']}%")
        dims = v["dimensions"]
        print(f"    R1={dims.get('R1',0)}% R2={dims.get('R2',0)}% R3={dims.get('R3',0)}% R4={dims.get('R4',0)}% R5={dims.get('R5',0)}% R6={dims.get('R6',0)}%")

    # Quality
    q = sc.get("quality")
    if q:
        print(f"\n  Quality (n={q['n']}):")
        print(f"    清晰度: {q['clarity_mean']}  建议: {q['actionability_mean']}")

    # Prudence + Refusal
    for k in ["prudence", "refusal"]:
        v = sc.get(k)
        if v:
            print(f"\n  {k} (n={v['n']}): 均值={v['mean']}  分布={v['dist']}")

    # Rules
    r = sc.get("rules")
    if r:
        print(f"\n  Rules (n={r['n']}):")
        print(f"    条文: {r['article_pct']}%  绝对化: {r['absolutist_pct']}%  元评论: {r['meta_pct']}%  追问: {r['followup_pct']}%")
        print(f"    拒答准确率: {r['refusal_accuracy']}%")

    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="生成评测分数卡")
    parser.add_argument("--run", required=True, help="eval/outputs/ 下的文件前缀 (如 baseline, sft)")
    parser.add_argument("--layer1", help="Layer 1 知识评测 JSON 路径")
    parser.add_argument("--output", help="输出 JSON 路径（可选）")
    args = parser.parse_args()

    sc = build(args.run, args.layer1)
    print_card(sc)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f"已保存: {args.output}")


if __name__ == "__main__":
    main()
