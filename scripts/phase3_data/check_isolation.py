#!/usr/bin/env python3
"""阶段三 · 训评隔离检查。训练样本 vs eval_v1.jsonl 指纹硬去重。"""
import json, re, hashlib, sys

def fingerprint(question: str) -> str:
    normalized = re.sub(r'[^\w]', '', question.lower().replace(' ', ''))
    return hashlib.md5(normalized.encode()).hexdigest()

def main():
    # 加载评测集指纹
    eval_fps = set()
    with open("eval/datasets/eval_v1.jsonl") as f:
        for line in f:
            if line.strip():
                q = json.loads(line)["question"]
                eval_fps.add(fingerprint(q))
    print(f"评测集: {len(eval_fps)} 条")

    # 检查训练样本
    import os, glob
    train_dir = "data/sft/05_train"
    overlap = []
    total = 0
    for fname in glob.glob(f"{train_dir}/**/*.jsonl", recursive=True):
        with open(fname) as f:
            for line in f:
                if not line.strip():
                    continue
                s = json.loads(line)
                q = s.get("input", s.get("question", ""))
                if not q:
                    continue
                total += 1
                fp = fingerprint(q)
                if fp in eval_fps:
                    overlap.append(q[:60])

    print(f"训练集: {total} 条")
    if overlap:
        print(f"❌ 重叠: {len(overlap)} 条!")
        for q in overlap:
            print(f"  {q}")
        sys.exit(1)
    else:
        print("✅ 零重叠，隔离通过")

if __name__ == "__main__":
    main()
