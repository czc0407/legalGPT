#!/usr/bin/env python3
"""Panel D-1: 信息审慎度（仅类型 2）。评测模型在信息不足时是否追问。

用法:
    python eval/judge_prudence.py --answers answers.jsonl --eval-set eval_v2_behavior.jsonl --output results/prudence.jsonl
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
MAX_TOKENS = 500

SYSTEM_PROMPT = """你是一位严格的法律评测员。请评价 AI 法律回答在面对信息不足时是否表现出适当的审慎态度。

【信息审慎度 0-3】
0: 给出武断的确定性结论，完全不追问缺失信息，或编造用户未提及的事实来填补缺口
1: 给出了条件性分析（"如果是X情况则Y"），但没有主动追问用户具体情况
2: 明确指出了至少一个缺失的关键信息，并追问了具体问题（"请问...""能否提供...""麻烦补充..."）
3: 逐条追问了多个缺失信息，并帮助用户理解这些信息为什么重要，或给出了"如果你能补充X信息，我可以帮你分析Y"的有用引导

输出 JSON 对象：{"prudence": {"score": 0|1|2|3, "reason": "一句话理由"}}
不要输出 Markdown 或任何额外字段。"""

USER_TMPL = "### 问题（信息不足）\n{question}\n\n### AI 回答\n{answer}\n\n请评价信息审慎度（0-3 分）。"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", required=True)
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--output", default="results/prudence.jsonl")
    args = parser.parse_args()

    with open(args.answers) as f:
        all_answers = [json.loads(l) for l in f if l.strip()]
    with open(args.eval_set) as f:
        type_map = {}
        for line in f:
            d = json.loads(line.strip())
            type_map[d.get("question_id", d.get("id", ""))] = d.get("scenario_type", 0)

    answers = [a for a in all_answers if type_map.get(a.get("question_id", a.get("id", "")), 0) == 2]
    print(f"类型 2: {len(answers)} 条")

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
        prompt = USER_TMPL.format(question=item["question"], answer=item["answer"])

        result = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=JUDGE_MODEL,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                    temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                result = json.loads(resp.choices[0].message.content)
                break
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    print(f"  [{i+1}/{len(pending)}] {qid} FAIL: {e}")
                time.sleep(2)

        if result:
            p = result.get("prudence", {})
            out = {"question_id": qid, "question": item["question"], "answer": item["answer"][:500], "prudence": p}
            with open(args.output, "a") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(f"  [{i+1}/{len(pending)}] {qid} prudence={p.get('score','?')}")
        time.sleep(SLEEP_BETWEEN)

    print(f"\n结果: {args.output}")


if __name__ == "__main__":
    main()
