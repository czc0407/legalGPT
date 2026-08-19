#!/usr/bin/env python3
"""Panel C: 质量维度打分（清晰度 + 建议可执行性）。0/1/2 量表，不看参考答案。

用法:
    python eval/judge_quality.py --answers answers.jsonl --eval-set disc_eval_v5.json --output results/quality.jsonl
"""
import json, os, sys, time, argparse
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts" / "config"))

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, MAX_RETRIES, SLEEP_BETWEEN

JUDGE_MODEL = "gpt-4o-mini"
TEMPERATURE = 0.0
MAX_TOKENS = 800

# ── System Prompt ────────────────────────────────────────────────
QUALITY_SYSTEM = """你是一位严格的法律咨询质量评审员。请独立评价以下 AI 法律回答的质量（不看任何参考答案）。

【清晰度 0-3】
0: 逻辑混乱，无法读懂，或大量堆砌术语不加解释，或包含元评论/自语
1: 能读懂，但以编号列表（\"1. 2. 3.\"）为主导结构，各点之间没有自然段落过渡
2: 以自然段落为主，偶尔穿插列表，整体流畅但有少量冗余或无关内容
3: 在 2 的基础上额外做到表达高效——没有科普式铺垫、没有重复论述、没有与核心问题无关的内容。每句话都对用户有用

【建议可执行性 0-3】
0: 无建议，或建议有害
1: 建议方向正确但笼统（"可以申请劳动仲裁"），完全没有具体细节
2: 给出了一定操作指引（如提到找什么部门），但缺少关键细节（材料/时限）
3: 完整的可执行步骤：找哪个部门 → 带什么材料 → 注意什么时限

注意：如果问题本身不需要行动建议（如纯法律知识问题），建议可执行性判为不适用，填写 null。

输出 JSON 对象：
{
  "clarity": {"score": 0|1|2|3, "reason": "一句话理由"},
  "actionability": {"score": 0|1|2|3|null, "reason": "一句话理由"}
}
不要输出 Markdown 或任何额外字段。"""

QUALITY_USER = """### 问题
{question}

### AI 回答
{answer}

请独立评价以上回答的清晰度和建议可执行性（0/1/2 分）。"""


def load_answers(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", required=True)
    parser.add_argument("--output", default="results/quality.jsonl")
    parser.add_argument("--max-samples", type=int)
    args = parser.parse_args()

    answers = load_answers(args.answers)
    print(f"加载: {len(answers)} 条回答")

    if args.max_samples:
        answers = answers[:args.max_samples]

    # 断点续传
    done_ids = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    done_ids.add(json.loads(line).get("question_id", ""))
        print(f"已完成: {len(done_ids)}")

    pending = [a for a in answers if a.get("question_id", a.get("id", "")) not in done_ids]
    print(f"待处理: {len(pending)}")

    if not pending:
        print("全部完成！")
        return

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    for i, item in enumerate(pending):
        qid = item.get("question_id", item.get("id", ""))
        question = item.get("question", "")
        answer = item.get("answer", "")

        prompt = QUALITY_USER.format(question=question, answer=answer)

        result = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=JUDGE_MODEL,
                    messages=[
                        {"role": "system", "content": QUALITY_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                result = json.loads(resp.choices[0].message.content)
                break
            except (json.JSONDecodeError, Exception) as e:
                if attempt == MAX_RETRIES - 1:
                    print(f"  [{i+1}/{len(pending)}] {qid} FAIL: {e}")
                time.sleep(2)

        if result:
            c = result.get("clarity", {}).get("score", "?")
            a = result.get("actionability", {}).get("score", "?")
            out = {
                "question_id": qid,
                "question": question,
                "answer": answer[:500],
                "clarity": result.get("clarity", {}),
                "actionability": result.get("actionability", {}),
            }
            with open(args.output, "a") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(f"  [{i+1}/{len(pending)}] {qid}  clarity={c} actionability={a}")

        time.sleep(SLEEP_BETWEEN)

    print(f"\n结果: {args.output}")


if __name__ == "__main__":
    main()
