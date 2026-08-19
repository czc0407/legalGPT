#!/usr/bin/env python3
"""对华律网抽样问题的标签进行 LLM 重分类，修正原始 title 错误。"""

import json
import os
import sys
import time
from collections import Counter
from openai import OpenAI

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
from llm_config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL
from classify_consultation import build_prompt, parse_response

INPUT_FILE = "data/sft/03_balanced/hualv_questions_to_label.jsonl"
OUTPUT_FILE = "data/sft/03_balanced/hualv_questions_relabeled.jsonl"
PROGRESS_FILE = "data/sft/03_balanced/hualv_relabel_progress.json"

BATCH_SIZE = 8
MAX_RETRIES = 3
SLEEP_BETWEEN = 0.5

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)

# 加载
with open(INPUT_FILE) as f:
    all_questions = [json.loads(l) for l in f if l.strip()]
print(f"加载 {len(all_questions)} 条")

# 恢复进度
done_ids = set()
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE) as f:
        done_ids = set(json.load(f).get("done_ids", []))
    print(f"恢复: 已完成 {len(done_ids)}")

existing = []
if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE) as f:
        for line in f:
            if line.strip():
                existing.append(json.loads(line))
                done_ids.add(existing[-1]["hualv_id"])
    print(f"已有输出: {len(existing)}")

pending = [q for q in all_questions if q["hualv_id"] not in done_ids]
print(f"待处理: {len(pending)}")

if not pending:
    print("全部完成！")
    # 即使全部完成也打印分布对比
    pass
else:
    total = len(pending)
    for batch_start in range(0, total, BATCH_SIZE):
        batch = pending[batch_start : batch_start + BATCH_SIZE]
        questions = [item["question"] for item in batch]
        prompt = build_prompt(questions)

        labels = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": "你是一个法律文书分类专家，输出严格JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                content = resp.choices[0].message.content or ""
                if content.strip():
                    labels = parse_response(content)
                    if labels:
                        break
            except Exception as e:
                print(f"  API 错误: {e}")
                time.sleep(2)

        if not labels:
            print(f"  批次 {batch_start} 分类失败，保留原标签")
            labels = [item["category"] for item in batch]
        if len(labels) != len(batch):
            labels = labels[:len(batch)] + [item["category"] for item in batch[len(labels):]]

        for item, label in zip(batch, labels):
            item["category_original"] = item["category"]
            item["category"] = label
            existing.append(item)
            done_ids.add(item["hualv_id"])

        # 保存
        with open(OUTPUT_FILE, "w") as f:
            for q in existing:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"done_ids": list(done_ids), "total": len(all_questions)}, f)

        if (batch_start + BATCH_SIZE) % 40 == 0 or batch_start + BATCH_SIZE >= total:
            print(f"  进度: {batch_start + len(batch)}/{total}")

        time.sleep(SLEEP_BETWEEN)

# ── 分布对比 ──
print(f"\n{'='*60}")
print(f"  标签变化对比")
print(f"{'='*60}")

old_dist = Counter(q.get("category_original", q["category"]) for q in existing)
new_dist = Counter(q["category"] for q in existing)
changed = sum(1 for q in existing if q.get("category_original") and q["category_original"] != q["category"])

print(f"  总变更: {changed}/{len(existing)} ({changed/max(len(existing),1)*100:.1f}%)\n")
print(f"  {'类别':<16s} {'原标签':>8s} {'新标签':>8s} {'变化':>8s}")
print(f"  {'-'*44}")
for cat in sorted(set(list(old_dist.keys()) + list(new_dist.keys()))):
    o = old_dist.get(cat, 0)
    n = new_dist.get(cat, 0)
    diff = n - o
    flag = f"+{diff}" if diff > 0 else str(diff)
    print(f"  {cat:<16s} {o:>8} {n:>8} {flag:>8}")

# 写回原文件（覆盖）
with open(INPUT_FILE, "w") as f:
    for q in existing:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")

print(f"\n  已写回: {INPUT_FILE}")
print(f"  Done.")
