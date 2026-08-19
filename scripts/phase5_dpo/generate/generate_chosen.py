#!/usr/bin/env python3
"""用强模型对 DPO 候选问题生成 chosen（理想回答）。

审慎度 chosen 用 PRUDENCE_CHOSEN（信息不足 → 条件化 + 追问），
拒答 chosen 用 PROMPT_D（礼貌拒答）。

用法:
    python scripts/phase5_dpo/generate_chosen.py \
        --input data/dpo/v0.2/dpo_rejected.jsonl \
        --output data/dpo/v0.2/dpo_pairs.jsonl \
        --model gpt-4o \
        [--limit 2]   # 只生成前 N 个，用于测试
"""
import json, os, sys, time, argparse
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, PROJECT_DIR)

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE
from dpo_prompts import (
    PRUDENCE_CHOSEN_V2_SYSTEM, PRUDENCE_CHOSEN_V2_USER,
    REFUSAL_CHOSEN_V2_SYSTEM, REFUSAL_CHOSEN_V2_USER, REFUSAL_SCENARIO_MAP,
)


def build_messages(item):
    """按维度构造 chosen 生成的 messages。"""
    dim = item["dimension"]
    if dim == "prudence":
        user = PRUDENCE_CHOSEN_V2_USER.replace("{question}", item["question"])
        return PRUDENCE_CHOSEN_V2_SYSTEM, user
    else:  # refusal
        subtype = item.get("subtype", "")
        scenario_type, specific_topic = REFUSAL_SCENARIO_MAP.get(
            subtype, ("D", "与法律无关的问题"))
        user = (REFUSAL_CHOSEN_V2_USER
                .replace("{scenario_type}", scenario_type)
                .replace("{specific_topic}", specific_topic)
                .replace("{user_input}", item["question"]))
        return REFUSAL_CHOSEN_V2_SYSTEM, user


def main():
    parser = argparse.ArgumentParser(description="强模型生成 chosen")
    parser.add_argument("--input", default="data/dpo/v0.2/dpo_rejected.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.2/dpo_pairs.jsonl")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 个（0=全部）")
    args = parser.parse_args()

    with open(args.input) as f:
        items = [json.loads(l) for l in f if l.strip()]
    if args.limit:
        items = items[:args.limit]
    print(f"待生成 chosen: {len(items)}")

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)

    # 断点续传（按 question 去重）
    done_questions = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for l in f:
                if l.strip():
                    done_questions.add(json.loads(l)["question"])
    pending = [i for i in items if i["question"] not in done_questions]
    print(f"已完成: {len(done_questions)}，待处理: {len(pending)}")

    for i, item in enumerate(pending):
        sys_prompt, user_prompt = build_messages(item)
        # 长度由 prompt 约束（参考 PROMPT_D 的"篇幅 X-Y 字"写法），不靠 max_tokens 硬截断
        max_tokens = 500
        chosen = None
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=args.model,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=max_tokens,
                )
                chosen = (resp.choices[0].message.content or "").strip()
                if chosen:
                    break
            except Exception as e:
                if attempt == 2:
                    print(f"  API 错误: {e}")
                time.sleep(2)

        if not chosen:
            print(f"  ❌ 生成失败: {item['question'][:40]}")
            continue

        out = dict(item)
        out["chosen"] = chosen

        with open(args.output, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

        if (i + 1) % 10 == 0 or i + 1 == len(pending):
            print(f"  进度: {i+1}/{len(pending)} | 近条 chosen 长度: {len(chosen)}")

        time.sleep(0.3)

    print(f"\n完成: {args.output}")


if __name__ == "__main__":
    main()
