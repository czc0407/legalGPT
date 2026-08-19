#!/usr/bin/env python3
"""审慎度偏好对：chosen = SFT 卡2 answer，rejected = P6 + P4 扰动（多 rejected）。

复用 perturb_dpo.py 的扰动函数（已修复 P6 模板化 / P4 错配）。

用法:
    python scripts/phase5_dpo/generate_prudence_rejected.py \
        [--input data/dpo/v0.5/prudence_input_v5.jsonl] \
        [--output data/dpo/v0.5/prudence_pairs_v5.jsonl]
"""
import json, os, sys, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts", "phase3_data"))

from perturb_dpo import perturb_p6, perturb_p4, check_valid, INSTRUCTION


def main():
    parser = argparse.ArgumentParser(description="审慎度偏好对（P6+P4 多 rejected）")
    parser.add_argument("--input", default="data/dpo/v0.5/prudence_input_v5.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.5/prudence_pairs_v5.jsonl")
    args = parser.parse_args()

    with open(args.input) as f:
        items = [json.loads(l) for l in f if l.strip()]
    print(f"审慎度 chosen: {len(items)} 条")

    pairs = []
    stats = {"P6": 0, "P4": 0, "跳过": 0}
    for it in items:
        q = it["question"]
        chosen = it["answer"]

        # P6 扰动（条件化→绝对化）
        rej_p6 = perturb_p6(chosen)
        if rej_p6 and check_valid(rej_p6, chosen):
            pairs.append({"instruction": INSTRUCTION, "input": q, "chosen": chosen, "rejected": rej_p6})
            stats["P6"] += 1

        # P4 扰动（编造事实）
        rej_p4 = perturb_p4(chosen, q)
        if rej_p4 and check_valid(rej_p4, chosen):
            pairs.append({"instruction": INSTRUCTION, "input": q, "chosen": chosen, "rejected": rej_p4})
            stats["P4"] += 1

        if not (rej_p6 or rej_p4):
            stats["跳过"] += 1

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"审慎度偏好对: {len(pairs)} 对 → {args.output}")
    print(f"  扰动统计: {stats}")


if __name__ == "__main__":
    main()
