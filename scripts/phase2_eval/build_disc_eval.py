#!/usr/bin/env python3
"""将 DISC 主观题改写为咨询场景评测集。

Q: 案例/法考问题 → 生活咨询场景
A: 保留法律判断 + 条文引用 + 结论，改写为 canonical 格式

用法:
    python scripts/phase2_eval/build_disc_eval.py --dry-run  # 先看3条
    python scripts/phase2_eval/build_disc_eval.py             # 全量 (200条)
"""
import json, os, sys, time, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, MAX_RETRIES, SLEEP_BETWEEN

MODEL = "deepseek-chat"
TEMPERATURE = 0.3
MAX_TOKENS = 2000

INPUT_FILE = "/tmp/disc_selected_150.json"
OUTPUT_FILE = "eval/datasets/disc_eval_v1.jsonl"

# ── 改写 System Prompt ──────────────────────────────────────────
REWRITE_SYSTEM = """你是一位法律文书改写专家。你的任务是将法律考试/判决书风格的问题和答案，改写为面向普通人的法律咨询服务。

【改写规则 — 问题（Q）】
- 原始 Q 可能是"请对以下案件做出分析"或咨询口吻（"我该怎么办"）
- 案例/判决类：改写为自然的生活咨询场景，保留所有关键法律事实，用日常语言表达
- 咨询类（已接近咨询口吻）：轻量润色即可，可适当扩展使表达更自然

【改写规则 — 答案（A）】
- 保留原文的全部法律判断、条文引用（含具体条款号）和结论。这些是专家写的，一个字都不能改
- 将表达形式从"判决书/教科书语言"改写为自然段落的咨询顾问口吻
- 结构遵循：理解用户处境 → 法律定性 → 法律依据与说理 → 结论与建议
- 用自然段落过渡，不要用标签分隔
- **开头多样化**：不要每条都以"我理解您/理解您的情况"开头。可以直接进入法律定性（如"这属于典型的合同纠纷"），也可以先从问题的关键事实切入（如"您提到的情况关键在于..."）。每条的开头应该不同
- 语言专业但易懂，面向普通用户
- 篇幅控制在 200-500 字

【严禁】
- 修改原文的法律结论、罪名认定、刑罚/赔偿责任
- 修改或删除原文中的法律名称和条文编号
- 添加原文中没有的法律依据或结论
- 使用"首先/其次/最后"等标签化结构词
- 编造任何原文中没有的事实细节
- 使用判决书语态（"法院最终判决""判决如下""判处""判令"等）——应改为咨询建议口吻（"你很可能""通常情况下""建议你主张""可以要求"等）。原文的具体刑期/金额可以转为"通常判 X-Y 年""约 X 个月工资"等区间或估算表达"""


REWRITE_USER = """请改写以下法律问答：

### 原始问题
{question}

### 原始答案
{answer}

请输出 JSON 格式：
{{"question": "改写后的问题", "answer": "改写后的答案"}}"""


def load_selected(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def classify_question(q: str) -> str:
    """返回原始问题类型，用于统计。"""
    import re
    if re.search(r'请对以下案件|请分析|请判断|请判决|请审理', q):
        return "case"
    if re.search(r'我|我的|怎么办|怎么[办处理]|如何|怎样|能不能|可以.*吗', q):
        return "consult"
    return "concept"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只跑 3 条验证")
    args = parser.parse_args()

    data = load_selected(INPUT_FILE)
    print(f"加载 {len(data)} 条")

    if args.dry_run:
        import random
        random.seed(42)
        # 每类各抽一条 + 额外一条随机
        cats = {}
        for d in data:
            cats.setdefault(classify_question(d['input']), []).append(d)
        data = []
        for k in sorted(cats):
            if cats[k]:
                data.append(random.choice(cats[k]))
        remaining = [d for d in sum(cats.values(), []) if d not in data]
        if remaining:
            data.append(random.choice(remaining))

    # 统计
    types = {}
    for d in data:
        types[classify_question(d['input'])] = types.get(classify_question(d['input']), 0) + 1
    print(f"  案例: {types.get('case', 0)}, 咨询: {types.get('consult', 0)}, 概念: {types.get('concept', 0)}")

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)

    # 断点续传
    done_ids = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            for line in f:
                if line.strip():
                    done_ids.add(json.loads(line).get("original_id", -1))

    pending = [d for d in data if d['id'] not in done_ids]
    print(f"已完成: {len(done_ids)}, 待处理: {len(pending)}")

    for i, item in enumerate(pending):
        prompt = REWRITE_USER.format(question=item['input'], answer=item['output'])

        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": REWRITE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content
                result = json.loads(raw)
                break
            except (json.JSONDecodeError, KeyError) as e:
                if attempt == MAX_RETRIES - 1:
                    print(f"  [{i+1}/{len(pending)}] id={item['id']} FAIL: {e}")
                    result = None
                time.sleep(2)

        if result and result.get("question") and result.get("answer"):
            q_len = len(result["question"])
            a_len = len(result["answer"])
            orig_type = classify_question(item['input'])
            print(f"  [{i+1}/{len(pending)}] id={item['id']} "
                  f"类型={orig_type}  Q={q_len}字 A={a_len}字  "
                  f"refs={len([c for c in ['《','》'] if c in result['answer']])//2}条引用")

            out = {
                "id": f"disc_eval_{item['id']:04d}",
                "original_id": item['id'],
                "question": result["question"],
                "answer": result["answer"],
                "scenario_type": 1,  # 改写后都是信息充分
                "source": "disc_rewrite",
            }
            with open(OUTPUT_FILE, "a") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

        time.sleep(SLEEP_BETWEEN)

    # 最终统计
    with open(OUTPUT_FILE) as f:
        final = [json.loads(l) for l in f if l.strip()]
    print(f"\n完成: {len(final)} 条")
    lens = [len(d['answer']) for d in final]
    print(f"  A 长度: 均值 {sum(lens)/len(lens):.0f} 中位 {sorted(lens)[len(lens)//2]} "
          f"范围 {min(lens)}-{max(lens)}")


if __name__ == "__main__":
    main()
