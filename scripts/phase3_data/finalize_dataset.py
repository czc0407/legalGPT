#!/usr/bin/env python3
"""阶段三 · 切分 + 版本登记。9:1 分层切分，生成 dataset_info.json。"""
import json, os, random
from collections import defaultdict

def stratified_split(samples: list[dict], val_ratio=0.1) -> tuple[list, list]:
    """按 category 分层 9:1 切分。"""
    by_cat = defaultdict(list)
    for s in samples:
        cat = s.get("category", s.get("label", "unknown"))
        # 从 input 或 question 中提取类别
        if cat == "unknown":
            # 尝试从 raw 文件中获取 category
            pass
        by_cat[cat].append(s)

    train, val = [], []
    for cat, items in by_cat.items():
        random.shuffle(items)
        n_val = max(1, int(len(items) * val_ratio))
        val.extend(items[:n_val])
        train.extend(items[n_val:])

    random.shuffle(train)
    random.shuffle(val)
    return train, val

def main():
    random.seed(42)

    # SFT split
    sft_file = "data/sft/05_train/train.jsonl"
    sft_dir = os.path.dirname(sft_file)
    all_sft = []
    with open(sft_file) as f:
        for line in f:
            if line.strip():
                all_sft.append(json.loads(line))
    train_sft, val_sft = stratified_split(all_sft)

    with open(os.path.join(sft_dir, "train.jsonl"), "w") as f:
        for s in train_sft:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(os.path.join(sft_dir, "val.jsonl"), "w") as f:
        for s in val_sft:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"SFT: train={len(train_sft)}, val={len(val_sft)}")

    # DPO split
    dpo_file = "data/dpo/v0.1/train.jsonl"
    dpo_dir = os.path.dirname(dpo_file)
    all_dpo = []
    with open(dpo_file) as f:
        for line in f:
            if line.strip():
                all_dpo.append(json.loads(line))
    train_dpo, val_dpo = stratified_split(all_dpo)

    with open(os.path.join(dpo_dir, "train.jsonl"), "w") as f:
        for s in train_dpo:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(os.path.join(dpo_dir, "val.jsonl"), "w") as f:
        for s in val_dpo:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"DPO: train={len(train_dpo)}, val={len(val_dpo)}")

    # dataset_info.json
    info = {
        "phase03_sft_v0_1": {
            "file_name": "sft/v0.1/train.jsonl",
            "formatting": "alpaca",
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        },
        "phase03_dpo_v0_1": {
            "file_name": "dpo/v0.1/train.jsonl",
            "formatting": "alpaca",
            "ranking": True,
            "columns": {"prompt": "instruction", "query": "input", "chosen": "chosen", "rejected": "rejected"},
        },
    }
    with open("dataset_info.json", "w") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print("dataset_info.json 已生成")

    # 版本卡
    version = {
        "version": "v0.1",
        "date": "2026-07-29",
        "sft_train": len(train_sft),
        "sft_val": len(val_sft),
        "dpo_train": len(train_dpo),
        "dpo_val": len(val_dpo),
    }
    os.makedirs("data/sft/04_cards", exist_ok=True)
    with open("data/sft/04_cards/VERSION", "w") as f:
        json.dump(version, f, ensure_ascii=False, indent=2)
    print(f"版本卡: data/sft/04_cards/VERSION")

if __name__ == "__main__":
    main()
