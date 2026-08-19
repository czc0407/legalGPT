#!/usr/bin/env python3
"""阶段三 · 卡 6：知识问答数据抽取。从 DISC knowledge QA 中筛选有引用+合适长度的样本。

用法:
    python scripts/phase3_data/build_knowledge_qa.py --smoke   # 10 条
    python scripts/phase3_data/build_knowledge_qa.py --full     # 500 条
"""
import json, re, random, argparse
import os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

INPUT_FILE = os.path.join(PROJECT_DIR, "data/sft/01_cleaned/DISC_knowledge_qa.jsonl")
OUTPUT_FILE = os.path.join(PROJECT_DIR, "data/sft/04_cards/card6_knowledge.jsonl")

# 筛选条件
MIN_LEN = 150
MAX_LEN = 800
MUST_HAVE_CITATION = True


def meets_criteria(item: dict) -> bool:
    a = item.get("response", "")
    if len(a) < MIN_LEN or len(a) > MAX_LEN:
        return False
    if MUST_HAVE_CITATION and not re.search(r"《[^》]+》", a):
        return False
    # 排除包含"首先/其次/最后"标签词的——这些不是简洁知识问答格式
    if re.search(r"首先.{0,20}其次|第一.{0,20}第二.{0,20}第三", a):
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    random.seed(42)

    # 加载并筛选
    all_items = []
    with open(INPUT_FILE) as f:
        for line in f:
            d = json.loads(line.strip())
            if meets_criteria(d):
                all_items.append(d)

    print(f"候选: {len(all_items)} 条 (筛选自 15,987)")

    if args.smoke:
        n = 10
    elif args.full:
        n = 500
    else:
        print("请指定 --smoke 或 --full")
        return

    selected = random.sample(all_items, min(n, len(all_items)))

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        for d in selected:
            out = {
                "id": f"sft_card6_{d['id']}",
                "card": 6,
                "source": "disc_knowledge_qa",
                "scenario_type": "knowledge",
                "category": d.get("type", ""),
                "question": d["query"],
                "answer": d["response"],
            }
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    print(f"已保存 {len(selected)} 条 → {OUTPUT_FILE}")

    # 快速统计
    lens = [len(d["response"]) for d in selected]
    refs = sum(1 for d in selected if re.search(r"《[^》]+》", d["response"]))
    print(f"长度: {sum(lens)//len(lens)} 均值 | 引用: {refs}/{len(selected)}")


if __name__ == "__main__":
    main()
