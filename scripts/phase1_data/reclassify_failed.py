#!/usr/bin/env python3
"""补分类：对 hualv_questions_to_label.jsonl 中 category_original 为空的条目重新分类。"""
import json, sys, os, time
from collections import Counter
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
from llm_config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL
from classify_consultation import build_prompt, parse_response
from openai import OpenAI

INPUT = "data/sft/03_balanced/hualv_questions_to_label.jsonl"
PROGRESS = "data/sft/03_balanced/hualv_failed_reclassify_progress.json"

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)

with open(INPUT) as f:
    data = [json.loads(l) for l in f if l.strip()]

failed_indices = [i for i, q in enumerate(data) if not q.get('category_original')]
print(f"待补分类: {len(failed_indices)} 条")

done_set = set()
if os.path.exists(PROGRESS):
    with open(PROGRESS) as f:
        done_set = set(json.load(f).get("done", []))
    print(f"已恢复: {len(done_set)} 条完成")

pending = [(i, data[i]) for i in failed_indices if i not in done_set]
print(f"实际待处理: {len(pending)}")

BATCH = 8
for batch_start in range(0, len(pending), BATCH):
    batch = pending[batch_start:batch_start+BATCH]
    questions = [q['question'] for _, q in batch]

    labels = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role":"system","content":"输出严格JSON。"},
                          {"role":"user","content":build_prompt(questions)}],
                temperature=0.1, max_tokens=500,
            )
            content = resp.choices[0].message.content or ""
            if content.strip():
                labels = parse_response(content)
                if labels: break
        except Exception as e:
            print(f"  API错误: {e}")
            time.sleep(2)

    if not labels:
        labels = [q['category'] for _, q in batch]

    for (idx, q), new_label in zip(batch, labels):
        q['category_original'] = q['category']
        if q['category'] != new_label:
            q['category'] = new_label
        done_set.add(idx)

    if (batch_start + BATCH) % 80 == 0:
        with open(INPUT, 'w') as f:
            for q in data:
                f.write(json.dumps(q, ensure_ascii=False) + '\n')
        with open(PROGRESS, 'w') as f:
            json.dump({"done": list(done_set)}, f)
        print(f"  进度: {batch_start+len(batch)}/{len(pending)}  已保存")

    time.sleep(0.5)

# 最终保存
with open(INPUT, 'w') as f:
    for q in data:
        f.write(json.dumps(q, ensure_ascii=False) + '\n')

new_dist = Counter(q['category'] for q in data)
changed = sum(1 for q in data if q.get('category_original') and q['category_original'] != q['category'])
print(f"\n完成: 总变更 {changed}/{len(data)}")
for cat, cnt in new_dist.most_common():
    print(f"  {cat}: {cnt}")
