#!/usr/bin/env python3
"""对卡 2「信息不足」问题的 answer（审慎度 chosen 候选）打分，筛掉审慎度低的样本。

复用 eval/judge_prudence.py 的 0-3 分审慎度标准：
  0: 武断下结论，完全不追问，或编造事实
  1: 条件性分析，但没主动追问
  2: 明确指出缺失信息 + 追问具体问题
  3: 逐条追问多个缺失信息 + 帮助理解重要性

筛掉 score < 2 的样本（score 0/1 不是好的审慎度 chosen）。

用法:
    python scripts/phase5_dpo/score_prudence_chosen.py \
        [--input data/dpo/v0.5/prudence_input_v5.jsonl] \
        [--output data/dpo/v0.5/prudence_scored_v5.jsonl]
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

SYSTEM_PROMPT = """你是一位严格的法律评测员。请评价 AI 法律回答在面对信息不足时是否表现出适当的审慎态度。

【信息审慎度 0-3】
0: 给出武断的确定性结论，完全不追问缺失信息，或编造用户未提及的事实来填补缺口
1: 给出了条件性分析（"如果是X情况则Y"），但没有主动追问用户具体情况
2: 明确指出了至少一个缺失的关键信息，并追问了具体问题（"请问...""能否提供...""麻烦补充..."）
3: 逐条追问了多个缺失信息，并帮助用户理解这些信息为什么重要，或给出了"如果你能补充X信息，我可以帮你分析Y"的有用引导

输出 JSON 对象：{"score": 0|1|2|3, "reason": "一句话理由"}
不要输出 Markdown 或任何额外字段。"""

VALID = {0, 1, 2, 3}


def parse_score(text):
    try:
        d = json.loads(text)
        s = d.get("score", d.get("prudence", {}).get("score"))
        if isinstance(s, int) and s in VALID:
            return s, d.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        pass
    return None, ""


def main():
    parser = argparse.ArgumentParser(description="审慎度 chosen 打分")
    parser.add_argument("--input", default="data/dpo/v0.5/prudence_input_v5.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.5/prudence_scored_v5.jsonl")
    parser.add_argument("--min-score", type=int, default=2, help="筛选阈值（默认筛掉 <2）")
    args = parser.parse_args()

    with open(args.input) as f:
        items = [json.loads(l) for l in f if l.strip()]
    print(f"待打分: {len(items)} 条")

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)

    # 断点续传（按 hualv_id）
    done = {}
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    done[d["hualv_id"]] = d

    pending = [i for i in items if i["hualv_id"] not in done]
    print(f"已完成: {len(done)}，待处理: {len(pending)}")

    if not pending:
        _finish(items, done, args.output, args.min_score)
        return

    failed = []
    for i, item in enumerate(pending):
        score, reason = None, ""
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=OPENKEY_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"### 问题（信息不足）\n{item['question']}\n\n### AI 回答\n{item['answer']}\n\n请评价信息审慎度（0-3 分）。"},
                    ],
                    temperature=0.0,
                    max_tokens=200,
                )
                score, reason = parse_score(resp.choices[0].message.content or "")
                if score is not None:
                    break
            except Exception as e:
                if attempt == 2:
                    print(f"  API 错误: {e}")
                time.sleep(2)

        if score is None:
            failed.append(item["hualv_id"])
            continue

        done[item["hualv_id"]] = {"hualv_id": item["hualv_id"], "question": item["question"],
                                  "answer": item["answer"], "score": score, "reason": reason}

        if (i + 1) % 50 == 0 or i + 1 == len(pending):
            with open(args.output, "w") as f:
                for it in items:
                    if it["hualv_id"] in done:
                        f.write(json.dumps(done[it["hualv_id"]], ensure_ascii=False) + "\n")
            dist = Counter(d["score"] for d in done.values())
            print(f"  进度: {i+1}/{len(pending)} | 分数分布 {dict(sorted(dist.items()))}")

        time.sleep(0.2)

    _finish(items, done, args.output, args.min_score)
    if failed:
        print(f"\n  ❌ 失败 {len(failed)} 条")


def _finish(items, done, output, min_score):
    with open(output, "w") as f:
        for it in items:
            if it["hualv_id"] in done:
                f.write(json.dumps(done[it["hualv_id"]], ensure_ascii=False) + "\n")
    dist = Counter(d["score"] for d in done.values())
    keep = sum(v for k, v in dist.items() if k >= min_score)
    print(f"\n=== 打分汇总 ===")
    for k, v in sorted(dist.items()):
        print(f"  score={k}: {v} 条")
    print(f"  → 保留（score>={min_score}）: {keep} 条")


if __name__ == "__main__":
    main()
