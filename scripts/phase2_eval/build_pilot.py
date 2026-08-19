#!/usr/bin/env python3
"""构建 30 条试点样本：从 eval_v1.jsonl 分层抽取 + 三模型混源生成回答。

用法:
    python scripts/build_pilot.py                    # 抽样本 + 生成回答
    python scripts/build_pilot.py --dry-run          # 只抽样本，不调 API
    python scripts/build_pilot.py --output pilot_with_answers.jsonl
"""
import json
import sys
import os
import time
import random
import argparse
from typing import Optional
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
from openai import OpenAI
from llm_config import (
    OPENKEY_API_KEY, OPENKEY_API_BASE,
    DEEPSEEK_API_KEY, DEEPSEEK_API_BASE,
    DEEPSEEK_MODEL, TEMPERATURE, MAX_TOKENS, MAX_RETRIES, SLEEP_BETWEEN,
)

# 三个模型：各生成 10 条
MODEL_CONFIGS = [
    {"name": "GPT-4o-mini", "model": "gpt-4o-mini", "api_key": OPENKEY_API_KEY, "api_base": OPENKEY_API_BASE, "count": 10},
    {"name": "GPT-4.1-nano", "model": "gpt-4.1-nano", "api_key": OPENKEY_API_KEY, "api_base": OPENKEY_API_BASE, "count": 10},
    {"name": "DeepSeek-V4-Flash", "model": DEEPSEEK_MODEL, "api_key": DEEPSEEK_API_KEY, "api_base": DEEPSEEK_API_BASE, "count": 10},
]

ANSWER_PROMPT = """你是一位专业的中国法律咨询助手。请针对以下用户问题，提供一份专业、完整的法律咨询回答。

要求：
1. 如果问题提供了足够的事实信息，请给出具体的法律分析和建议
2. 如果问题信息不足，请指出需要补充哪些信息，并给出基于现有信息的初步分析
3. 如果涉及多个法律关系，请逐一分析
4. 引用相关法律名称（如《劳动合同法》《民法典》等），但不编造具体条文编号
5. 建议应具体、可执行，让用户知道下一步该做什么
6. 语气专业但平易近人，用通俗语言解释法律概念

用户问题：
{question}

请直接输出回答内容，不要加"回答："等前缀。"""


def load_eval_set(path: str = "eval/datasets/eval_v1.jsonl") -> list[dict]:
    """加载冻结评测集，排除类型 6。"""
    samples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("scenario_type") != 6:
                samples.append(d)
    return samples


def select_pilot(samples: list[dict], n: int = 30) -> list[dict]:
    """分层抽取试点样本：确保 11 类 + 3 场景均有覆盖。"""
    # 按 (category, scenario_type) 分组
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for s in samples:
        key = (s["category"], s["scenario_type"])
        cells[key].append(s)

    # 按每个 cell 的样本数升序排列（优先从稀缺 cell 抽取）
    cell_keys = sorted(cells.keys(), key=lambda k: len(cells[k]))

    selected = []
    used_ids = set()

    # 第一轮：每个 cell 抽 1 条
    for key in cell_keys:
        if len(selected) >= n:
            break
        for s in cells[key]:
            if s["question_id"] not in used_ids:
                selected.append(s)
                used_ids.add(s["question_id"])
                break

    # 第二轮：如果还不够 30（不太可能，33 cells 各 1 条 = 33 ≥ 30）
    round2_keys = sorted(cells.keys(), key=lambda k: len(cells[k]), reverse=True)
    while len(selected) < n:
        for key in round2_keys:
            if len(selected) >= n:
                break
            for s in cells[key]:
                if s["question_id"] not in used_ids:
                    selected.append(s)
                    used_ids.add(s["question_id"])
                    break

    # 截断到 n，shuffle 一下
    selected = selected[:n]
    random.shuffle(selected)

    return selected


def assign_models(samples: list[dict]) -> list[dict]:
    """将 30 条样本分配给三个模型（各 10 条），保持类型和类别均衡。"""
    # 按 scenario_type 分层后轮流分配
    buckets: dict[int, list[dict]] = defaultdict(list)
    for s in samples:
        buckets[s["scenario_type"]].append(s)

    assignments = []
    model_idx = 0
    # 轮流从每个类型中取
    while any(buckets.values()):
        for st in [1, 2, 3]:
            if buckets[st]:
                s = buckets[st].pop(0)
                cfg = MODEL_CONFIGS[model_idx % 3]
                assignments.append({**s, "model_name": cfg["name"], "model_id": cfg["model"],
                                     "api_key": cfg["api_key"], "api_base": cfg["api_base"]})
                model_idx += 1

    return assignments


def generate_answer(item: dict) -> Optional[str]:
    """调用模型 API 生成回答。"""
    client = OpenAI(api_key=item["api_key"], base_url=item["api_base"])
    prompt = ANSWER_PROMPT.format(question=item["question"])

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=item["model_id"],
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"    重试 {attempt + 1}/{MAX_RETRIES}: {e}")
            time.sleep(SLEEP_BETWEEN * (attempt + 1))
    return None


def print_distribution(samples: list[dict]):
    """打印试点样本分布。"""
    cat_dist = defaultdict(lambda: defaultdict(int))
    model_dist = defaultdict(int)
    type_dist = defaultdict(int)
    for s in samples:
        cat_dist[s["category"]][s["scenario_type"]] += 1
        if "model_name" in s:
            model_dist[s["model_name"]] += 1
        type_dist[s["scenario_type"]] += 1

    print("\n场景类型分布:")
    for t in [1, 2, 3]:
        print(f"  类型 {t}: {type_dist[t]} 条")
    if model_dist:
        print(f"\n模型分配: {dict(model_dist)}")
    print(f"\n类别 × 场景分布:")
    for cat in sorted(cat_dist.keys()):
        parts = [f"T{t}={cat_dist[cat][t]}" for t in [1, 2, 3]]
        print(f"  {cat}: {', '.join(parts)}")


def main():
    parser = argparse.ArgumentParser(description="构建 30 条试点样本")
    parser.add_argument("--dry-run", action="store_true", help="只抽样本不打 API")
    parser.add_argument("--output", default="eval/outputs/pilot_with_answers.jsonl", help="输出文件")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    # 1. 加载 + 抽取
    print("加载 eval_v1.jsonl...")
    all_samples = load_eval_set()
    print(f"  正常样本（排除类型6）: {len(all_samples)} 条")

    pilot = select_pilot(all_samples, n=30)
    print(f"\n抽取试点: {len(pilot)} 条")
    print_distribution(pilot)

    if args.dry_run:
        # 输出选中的 question_id 列表
        print("\n--- dry-run: 不调用 API ---")
        for i, s in enumerate(pilot):
            print(f"  [{i+1}] {s['question_id']} [{s['category']}] type={s['scenario_type']}")
        return

    # 2. 分配模型
    pilot = assign_models(pilot)
    print(f"\n模型分配完成")
    print_distribution(pilot)

    # 3. 调用 API 生成回答
    print(f"\n生成回答...")
    results = []
    for i, item in enumerate(pilot):
        qid = item["question_id"]
        model_name = item["model_name"]
        print(f"  [{i+1}/30] {qid} via {model_name}...", end=" ", flush=True)

        answer = generate_answer(item)
        if answer:
            results.append({
                "question_id": qid,
                "question": item["question"],
                "category": item["category"],
                "scenario_type": item["scenario_type"],
                "answer": answer,
                "answer_model": item["model_id"],
                "legal_concepts": item.get("legal_concepts", []),
            })
            print(f"OK ({len(answer)} chars)")
        else:
            print("FAIL")

        time.sleep(SLEEP_BETWEEN)

    # 4. 输出
    print(f"\n成功: {len(results)}/30")
    with open(args.output, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"结果写入: {args.output}")


if __name__ == "__main__":
    main()
