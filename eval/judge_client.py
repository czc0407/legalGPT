"""LLM-Judge 打分客户端。调 OpenKey API，支持 CoT + 锚定 + 多次采样 + 断点续传。"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

from openai import OpenAI

from eval.config import (
    JUDGE_MODEL,
    JUDGE_TEMPERATURE,
    JUDGE_MAX_TOKENS,
    JUDGE_MULTI_RUN,
    OUTPUTS_DIR,
)

# 从项目 llm_config 拿 API key
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "config"))
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, MAX_RETRIES, SLEEP_BETWEEN

JUDGE_SYSTEM_PROMPT = """你是一位法律咨询质量评审员。请评价以下法律 AI 的回答质量。

请逐维度先给出判断理由，再给出 1-5 的分数。评分尺度参考以下锚定示例：

【1分示例 — 法律结论严重错误】
用户问题：公司拖欠工资三个月，没有签劳动合同，现在要求我离职，我应该怎么办？
模型回答：您好，根据相关法律规定，您可以向公安机关报案，要求追究老板的刑事责任。拖欠工资属于诈骗行为，公安机关会立案处理。
→ 准确性=1：故意拖欠工资≠刑事诈骗，法律定性完全错误

【5分示例 — 推理完整、建议可操作】
用户问题：在工地上干活摔伤了，老板不给报工伤也不赔钱，该怎么办？
模型回答：您在工地受伤后老板拒绝处理，这属于劳动工伤纠纷，核心在于能否证明劳动关系以及伤情是否构成工伤。根据《工伤保险条例》和《劳动法》，用人单位有义务为劳动者缴纳工伤保险并协助认定赔偿。如果您能提供工资记录、工友证言、考勤记录等，就可以证明事实劳动关系，享受工伤保险待遇。建议您尽快做三件事：保留全部医疗记录和费用票据；收集聊天记录、转账记录、现场照片等工作证据；向当地人社局提交工伤认定申请。老板不配合不影响人社部门主动调查。认定被拒或赔偿不到位可申请劳动仲裁，再向法院起诉。注意工伤认定有一年时效，从受伤日起算，请尽快行动。
→ 准确性=5, 完整性=5, 清晰度=5, 依据合理性=5, 建议可执行性=5

---

【评分维度及判断焦点】

1. 准确性（1-5）：回答中的法律判断是否正确？是否存在法律概念错误或误导性陈述？
   判断焦点：法律结论是否站得住脚

2. 完整性（1-5）：回答是否覆盖了用户问题的核心法律要点？
   判断焦点：是否遗漏了影响用户决策的关键方面

3. 清晰度（1-5）：逻辑结构是否清晰，普通用户能否理解？
   判断焦点：推理过程是否易懂、自然流畅（注意：不是检查是否用了标签词，canonical 格式本身不使用标签词）

4. 依据合理性（1-5）：援引的法律名称/概念是否契合具体情境？
   判断焦点：引用的法律是否与案情匹配（而非评估编号是否正确，本项目不要求条文编号）

5. 建议可执行性（1-5）：是否给出了用户可以具体行动的下一步建议？
   判断焦点：用户看完知道"下一步做什么"吗

请先对每个维度写一句话的判断理由，再给出分数。输出严格按以下 JSON 格式，不要输出其他内容：
{
  "准确性": {"理由": "...", "分数": 1-5},
  "完整性": {"理由": "...", "分数": 1-5},
  "清晰度": {"理由": "...", "分数": 1-5},
  "依据合理性": {"理由": "...", "分数": 1-5},
  "建议可执行性": {"理由": "...", "分数": 1-5}
}"""

DIMENSIONS = ["准确性", "完整性", "清晰度", "依据合理性", "建议可执行性"]


def build_judge_prompt(question: str, answer: str) -> tuple[str, str]:
    """构建 Judge 的 system + user prompt。"""
    user = f"【用户问题】\n{question}\n\n【模型回答】\n{answer}"
    return JUDGE_SYSTEM_PROMPT, user


def _parse_response(content: str) -> dict | None:
    """解析 Judge 返回的 JSON。失败返回 None。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    import re
    m = re.search(r'\{[\s\S]*\}', content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _call_judge_once(client: OpenAI, question: str, answer: str, model: str = JUDGE_MODEL) -> dict | None:
    """单次调用 Judge API。返回解析后的 dict 或 None。"""
    system_prompt, user_prompt = build_judge_prompt(question, answer)

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=JUDGE_TEMPERATURE,
                max_tokens=JUDGE_MAX_TOKENS,
            )
            content = resp.choices[0].message.content or ""
            parsed = _parse_response(content)
            if parsed:
                valid = all(
                    d in parsed
                    and isinstance(parsed[d], dict)
                    and "分数" in parsed[d]
                    and isinstance(parsed[d]["分数"], (int, float))
                    and 1 <= parsed[d]["分数"] <= 5
                    for d in DIMENSIONS
                )
                if valid:
                    return parsed
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(3 * (attempt + 1))
            else:
                print(f"  Judge API 最终失败: {e}")
    return None


def score_one(
    question: str, answer: str, client: OpenAI, model: str = JUDGE_MODEL, multi_run: int = JUDGE_MULTI_RUN
) -> dict | None:
    """对一条回答打分。multi_run 次采样取各维均值。"""
    all_scores = {d: [] for d in DIMENSIONS}
    all_reasons = {d: [] for d in DIMENSIONS}

    for _ in range(multi_run):
        result = _call_judge_once(client, question, answer, model)
        if result:
            for d in DIMENSIONS:
                all_scores[d].append(result[d]["分数"])
                all_reasons[d].append(result[d].get("理由", ""))
        time.sleep(SLEEP_BETWEEN)

    if not all_scores[DIMENSIONS[0]]:
        return None

    return {
        d: {
            "理由": all_reasons[d][0],
            "分数": round(sum(all_scores[d]) / len(all_scores[d]), 1),
            "采样次数": len(all_scores[d]),
        }
        for d in DIMENSIONS
    }


def score_batch(answers: list[dict], run_name: str) -> list[dict]:
    """批量打分，支持断点续传。"""
    output_dir = OUTPUTS_DIR / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "judge_results.jsonl"

    # 恢复已完成条目
    done_ids = set()
    results = []
    if results_path.exists():
        with open(results_path) as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    results.append(item)
                    done_ids.add(item["question_id"])

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    pending = [a for a in answers if a["question_id"] not in done_ids]
    total = len(pending)

    print(f"Judge ({JUDGE_MODEL}): 已完成 {len(done_ids)}，待处理 {total}")
    if not pending:
        return results

    for i, item in enumerate(pending):
        judge_scores = score_one(item["question"], item["answer"], client)

        result = {
            "question_id": item["question_id"],
            "judge_scores": judge_scores,
        }
        results.append(result)

        if (i + 1) % 5 == 0 or i == total - 1:
            with open(results_path, "w") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

        status = f"分数={judge_scores['准确性']['分数'] if judge_scores else 'FAIL'}"
        print(f"  [{i + 1}/{total}] {item['question_id']}  {status}")

        time.sleep(SLEEP_BETWEEN)

    success = sum(1 for r in results if r["judge_scores"] is not None)
    print(f"Judge 完成: {success}/{len(results)} 成功")
    return results
