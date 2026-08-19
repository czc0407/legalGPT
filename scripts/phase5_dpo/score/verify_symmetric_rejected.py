#!/usr/bin/env python3
"""验证 v3 对正常咨询问题的输出是否「过度拒答/追问」，筛选对称方向 rejected。

对称方向要的是「该给答案却拒答/追问」的真实失败样本。但 v3 的退化不止这一种
（还有法律依据错误、内容重复等，§9.7 采样发现），必须筛掉，保证 rejected 信号纯净。

判断三类：
- 过度拒答追问：拒绝了用户或只追问缺失信息，没给实质法律分析 → 保留（作 rejected）
- 正常回答：给了实质法律分析 → 剔除（v3 没退化，不能作 rejected）
- 其他退化：答了但法律错误/重复/答非所问 → 剔除（信号不纯）

用法:
    python scripts/phase5_dpo/verify_symmetric_rejected.py \
        [--input data/dpo/v0.4/symmetric_v3_rejected_v4.jsonl] \
        [--output data/dpo/v0.4/symmetric_rejected_v4_filtered.jsonl]
"""
import json, os, sys, time, argparse
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, PROJECT_DIR)

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, OPENKEY_MODEL

SYSTEM_PROMPT = """你是法律数据标注专家。给定一个正常法律咨询问题（本应给出完整法律分析）和一个模型回答，判断这个回答的性质。

判断标准：
1. **过度拒答追问**：回答拒绝或回避了用户（"我无法为您…""建议您咨询律师"），或者只追问缺失信息（"需要您确认…"）而没有给出实质法律分析。这类是「该给答案却拒答/追问」。
2. **正常回答**：给出了实质的法律分析（法条、定性、结论、建议），属于正常咨询回答。
3. **其他退化**：回答了，但法律依据错误、内容重复啰嗦、或明显答非所问。

只输出一个词：过度拒答追问、正常回答、其他退化。不要输出其他内容。"""

VALID = {"过度拒答追问", "正常回答", "其他退化"}


def parse_single(text):
    if not text or not text.strip():
        return None
    text = text.strip()
    for label in VALID:
        if label in text:
            return label
    return None


def main():
    parser = argparse.ArgumentParser(description="验证 v3 输出是否过度拒答")
    parser.add_argument("--input", default="data/dpo/v0.4/symmetric_v3_rejected_v4.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.4/symmetric_rejected_v4_filtered.jsonl")
    args = parser.parse_args()

    with open(args.input) as f:
        items = [json.loads(l) for l in f if l.strip()]
    print(f"v3 推理结果: {len(items)} 条")

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)

    # 断点续传（按 question）
    done = {}
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    done[d["question"]] = d["judgment"]

    pending = [i for i in items if i["question"] not in done]
    print(f"已完成: {len(done)}，待处理: {len(pending)}")

    if not pending:
        _finish(items, done, args.output)
        return

    failed = []
    for i, item in enumerate(pending):
        label = None
        # 只把回答喂给 LLM（问题 + 回答一起，让模型判断是否该给答案却拒答）
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=OPENKEY_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"【问题】{item['question']}\n【回答】{item['rejected'][:800]}"},
                    ],
                    temperature=0.0,
                    max_tokens=20,
                )
                content = resp.choices[0].message.content or ""
                label = parse_single(content)
                if label:
                    break
            except Exception as e:
                if attempt == 2:
                    print(f"  API 错误: {e}")
                time.sleep(2)

        if label is None:
            failed.append(item["question"][:30])
            continue

        done[item["question"]] = label

        if (i + 1) % 50 == 0 or i + 1 == len(pending):
            _write(items, done, args.output)
            dist = Counter(done.values())
            print(f"  进度: {i+1}/{len(pending)} | {dict(dist)}")

        time.sleep(0.2)

    _finish(items, done, args.output)
    if failed:
        print(f"\n  ❌ 失败 {len(failed)} 条")


def _write(items, done, output):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        for it in items:
            if it["question"] in done:
                f.write(json.dumps({
                    "question": it["question"],
                    "rejected": it["rejected"],
                    "judgment": done[it["question"]],
                }, ensure_ascii=False) + "\n")


def _finish(items, done, output):
    _write(items, done, output)
    dist = Counter(done.values())
    print(f"\n=== 验证汇总 ===")
    for k, v in dist.most_common():
        print(f"  {k}: {v}")
    keep = dist.get("过度拒答追问", 0)
    print(f"  → 可作对称 rejected 的「过度拒答追问」: {keep} 条")


if __name__ == "__main__":
    main()
