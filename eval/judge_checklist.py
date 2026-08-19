#!/usr/bin/env python3
"""Panel B: Checklist 判定（准确性 + 完整性）。对比参考答案，逐项判定 satisfied/violated/unknown。

用法:
    python eval/judge_checklist.py --answers answers.jsonl --eval-set disc_eval_v5.json --output results/checklist.json
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
MAX_TOKENS = 1000

# ── System Prompt ────────────────────────────────────────────────
CHECKLIST_SYSTEM = """你是一位严格的法律评测员。你的任务是对比以下"模型回答"和"参考答案"，逐项判定模型回答是否满足要求。

对于每个检查项，你必须输出以下判定之一：
- "satisfied"：模型回答满足了该检查项的要求
- "violated"：模型回答违反了该检查项的要求
- "unknown"：根据提供的信息无法确定

判定规则：
1. 只对比核心法律内容（定性、依据、结论），不纠结措辞差异
2. 如果模型回答的结论方向与参考答案一致，即使表述不同，应判为 satisfied
3. 如果参考答案中有具体金额或刑期，模型回答写了"具体金额需根据实际情况计算"等合理表述，应判为 satisfied（不要求数字精确匹配）
4. 模型回答如果以不同表述覆盖了参考答案同一个要点（等价覆盖），应判为 satisfied，不要求逐字一致
5. 如果模型回答中完全没有涉及该检查项的内容，判为 violated
6. 如果模型回答模糊不清、无法判断，判为 unknown

请输出一个 JSON 对象：
{
  "R1": {"verdict": "satisfied|violated|unknown", "reason": "一句话理由"},
  "R2": {"verdict": "...", "reason": "..."},
  ...
}
不要输出 Markdown 或任何额外字段。"""

CHECKLIST_USER = """### 问题
{question}

### 参考答案
{reference}

### 模型回答
{answer}

请对以下检查项逐项判定：

R1: 法律定性是否与参考答案一致？
R2: 引用的法律名称是否与参考答案一致？注意：只比对法律名称（如《民法典》《劳动合同法》），不要求条文编号一致。如果模型引用了恰当的法律名称，即使没有写出条文号，也应判定为 satisfied
R3: 案件事实认定是否与参考答案一致？
R4: 最终法律结论是否与参考答案一致？
R5: 是否覆盖了参考答案的所有主要法律要点？
R6: 是否遗漏了影响结论的关键法律要素？"""


def load_answers(path: str) -> list[dict]:
    """加载模型回答 JSONL。"""
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def load_eval_set(path: str) -> dict:
    """加载评测集（含参考答案），返回 question_id -> 参考答案映射。"""
    # Support both JSON array and JSONL
    refs = {}
    with open(path) as f:
        text = f.read().strip()
    if text.startswith("["):
        data = json.loads(text)
    else:
        data = [json.loads(l) for l in text.split("\n") if l.strip()]
    for d in data:
        refs[d.get("id", d.get("question_id", ""))] = d
    return refs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", required=True, help="模型回答 JSONL")
    parser.add_argument("--eval-set", required=True, help="DISC 改写集 JSON")
    parser.add_argument("--output", default="results/checklist.jsonl")
    parser.add_argument("--max-samples", type=int, help="限制样本数测试")
    args = parser.parse_args()

    answers = load_answers(args.answers)
    refs = load_eval_set(args.eval_set)
    print(f"加载: {len(answers)} 条回答, {len(refs)} 条参考答案")

    if args.max_samples:
        answers = answers[:args.max_samples]

    # 过滤：只评测有参考答案的
    matchable = [a for a in answers if a.get("question_id", a.get("id", "")) in refs]
    print(f"可评测: {len(matchable)} 条 (有参考答案)")

    # 断点续传
    done_ids = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    done_ids.add(json.loads(line).get("question_id", ""))
        print(f"已完成: {len(done_ids)}")

    pending = [a for a in matchable if a.get("question_id", a.get("id", "")) not in done_ids]
    print(f"待处理: {len(pending)}")

    if not pending:
        print("全部完成！")
        return

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    for i, item in enumerate(pending):
        qid = item.get("question_id", item.get("id", ""))
        ref = refs.get(qid)
        if not ref:
            continue

        question = item.get("question", ref.get("question", ""))
        answer = item.get("answer", "")
        reference = ref.get("answer", ref.get("reference", ""))

        prompt = CHECKLIST_USER.format(question=question, reference=reference, answer=answer)

        result = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=JUDGE_MODEL,
                    messages=[
                        {"role": "system", "content": CHECKLIST_SYSTEM},
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
            out = {
                "question_id": qid,
                "question": question,
                "answer": answer[:500],
                "reference": reference[:500],
                "judgments": result,
            }
            with open(args.output, "a") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

            # Quick stats
            n_sat = sum(1 for k, v in result.items() if isinstance(v, dict) and v.get("verdict") == "satisfied")
            n_vio = sum(1 for k, v in result.items() if isinstance(v, dict) and v.get("verdict") == "violated")
            n_unk = sum(1 for k, v in result.items() if isinstance(v, dict) and v.get("verdict") == "unknown")
            print(f"  [{i+1}/{len(pending)}] {qid}  sat={n_sat} vio={n_vio} unk={n_unk}")

        time.sleep(SLEEP_BETWEEN)

    print(f"\n结果: {args.output}")


if __name__ == "__main__":
    main()
