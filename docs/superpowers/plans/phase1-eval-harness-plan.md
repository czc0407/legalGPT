# 阶段一：评测框架搭建 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建法律咨询回答评测框架，输入模型回答 JSONL，输出规则指标 + LLM-Judge 五维打分的分数卡。

**Architecture:** 六个独立模块，通过 `eval.py` CLI 串联。规则检测不调模型（毫秒级），LLM-Judge 调 OpenKey API 并支持断点续传。中间产物落盘 `outputs/{run_name}/`，支持单独重跑某一步。

**Tech Stack:** Python 3.10+, OpenAI SDK (openai>=1.0), 复用项目已有 `scripts/llm_config.py` 的 API 配置

## Global Constraints

- 所有新文件放在 `eval/` 目录下，不修改 `scripts/` 下已有文件
- instruction 模板以 `scripts/generate_hualv_answers.py` 的 `SYSTEM_PROMPT` 为唯一事实来源
- Judge 模型默认 `gpt-4o-mini`，通过 `config.py` 一行切换
- 规则检测函数输入均为 `answer: str`，返回 `dict`
- LLM-Judge 输出格式为 `{"维度名": {"理由": str, "分数": int}}`
- 温度=0.0，多次采样默认 3 次
- 所有 API 调用必须含重试逻辑（至少 3 次）

---

### Task 1: `eval/config.py` — 集中配置

**Files:**
- Create: `eval/__init__.py`（空文件）
- Create: `eval/config.py`

**Interfaces:**
- Produces: 以下所有 Task 的配置来源

- [ ] **Step 1: 创建 `eval/` 目录和空 `__init__.py`**

```bash
mkdir -p eval
touch eval/__init__.py
```

- [ ] **Step 2: 编写 `eval/config.py`**

```python
"""评测框架配置。改参数只改此文件。"""
from pathlib import Path

# ── Judge 模型（改一行切换） ────────────────────────────────────────
JUDGE_MODEL = "gpt-4o-mini"         # 备选: "gpt-4.1-nano"

# ── 打分参数 ────────────────────────────────────────────────────────
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 500
JUDGE_MULTI_RUN = 3

# ── 规则检测：正则 ──────────────────────────────────────────────────
ABSOLUTIST_PATTERNS = ["一定", "必然", "肯定", "毫无疑问", "绝对"]
HEDGING_PATTERNS = ["建议咨询专业律师", "请咨询律师", "建议委托律师"]
ARTICLE_PATTERN = r"第[零一二三四五六七八九十百千0-9]+[条条款项]"
REFUSAL_KEYWORDS = ["无法", "超出能力", "不能代替", "无法回答", "无法代为"]

# ── 输出 ────────────────────────────────────────────────────────────
OUTPUTS_DIR = Path("eval/outputs")
```

- [ ] **Step 3: 验证配置可导入**

```bash
python -c "from eval.config import JUDGE_MODEL, JUDGE_TEMPERATURE, ARTICLE_PATTERN; print(f'Judge={JUDGE_MODEL}, Temp={JUDGE_TEMPERATURE}')"
```

Expected output: `Judge=gpt-4o-mini, Temp=0.0`

- [ ] **Step 4: Commit**

```bash
git add eval/__init__.py eval/config.py
git commit -m "feat: add eval config module"
```

---

### Task 2: `eval/prompt_template.py` — 固化 instruction 模板

**Files:**
- Create: `eval/prompt_template.py`

**Interfaces:**
- Produces: `EVAL_INSTRUCTION: str`, `format_prompt(question: str) -> str`
- 事实来源: `scripts/generate_hualv_answers.py` 的 `SYSTEM_PROMPT`

- [ ] **Step 1: 编写 `eval/prompt_template.py`**

```python
"""固化 instruction 模板。内容与 generate_hualv_answers.py 的 SYSTEM_PROMPT 保持一致。

事实来源，后续调 prompt 只改生成脚本，此文件同步更新。
SFT 数据构造脚本和评测框架均引用此模块。
"""

EVAL_INSTRUCTION = (
    "你是一位专业的中国法律咨询顾问。你的回答需要体现清晰的法律推理过程，"
    "让用户不仅知道"结论是什么"，还能理解"为什么是这个结论"。\n\n"
    "【回答结构】\n"
    "你的回答应自然包含以下要素（不要用标签分隔，而是用自然段落过渡）：\n"
    "1. 理解用户处境 — 用一两句话概括你理解到的核心问题\n"
    "2. 法律定性 — 这个问题在法律上属于什么范畴，涉及哪些法律关系\n"
    "3. 法律依据与说理 — 引用适用法律的名称（如《民法典》《劳动合同法》），"
    "说明该法律为什么适用、如何适用到用户的具体情况。这是回答的核心部分\n"
    "4. 结论与建议 — 给出明确、可操作的后续步骤\n\n"
    "【格式要求】\n"
    "- 篇幅严格控制在 200-300 字，超过 350 字即为不合格\n"
    "- 语言专业但易懂，面向普通用户\n"
    "- 引用法律名称时使用书名号，不给出具体条文编号\n"
    "- 不确定的法律名称不要编造，可以说"根据相关法律规定"\n"
    "- 严禁编造任何精确数据（赔偿金额、统计数字、百分比、年份标准等），"
    "可以说"具体金额需根据当地标准计算"\n"
    "- 不使用"大前提""小前提""结论""首先/其次/再次/最后"等标签化结构词\n"
    "- 严禁编造用户未提及的案情细节\n"
    "- 信息不足时，提示用户补充，但不要因此把整篇回答变成提问"
)


def format_prompt(question: str) -> str:
    """构建与训练时一致的推理 prompt。"""
    return f"{EVAL_INSTRUCTION}\n\n用户问题：{question}"
```

- [ ] **Step 2: 验证 `EVAL_INSTRUCTION` 与生成脚本一致**

```bash
python -c "
from scripts.generate_hualv_answers import SYSTEM_PROMPT
from eval.prompt_template import EVAL_INSTRUCTION
assert SYSTEM_PROMPT == EVAL_INSTRUCTION, 'MISMATCH! prompt_template.py differs from generate_hualv_answers.py'
print('OK: prompt_template matches generate_hualv_answers SYSTEM_PROMPT')
"
```

Expected output: `OK: prompt_template matches generate_hualv_answers SYSTEM_PROMPT`

- [ ] **Step 3: 验证 `format_prompt` 输出格式**

```bash
python -c "
from eval.prompt_template import format_prompt
result = format_prompt('公司拖欠工资怎么办')
assert '公司拖欠工资怎么办' in result
assert '用户问题' in result
print('OK: format_prompt works')
print(result[:200])
"
```

- [ ] **Step 4: Commit**

```bash
git add eval/prompt_template.py
git commit -m "feat: add prompt template module"
```

---

### Task 3: `eval/rule_checks.py` — 规则指标检测

**Files:**
- Create: `eval/rule_checks.py`

**Interfaces:**
- Produces:
  - `check_article_citation(text: str) -> dict` — `{"label": bool, "count": int, "detail": list[str]}`
  - `check_absolutist(text: str) -> dict` — `{"label": bool, "count": int, "detail": list[str]}`
  - `check_refusal(answer: str) -> bool` — 是否为拒答
  - `evaluate_refusal(answers: list[dict]) -> dict` — `{"false_negative": int, "false_positive": int, "accuracy": float, ...}`
  - `check_hedging(text: str) -> dict` — `{"label": bool, "count": int, "detail": list[str]}`
  - `run_all_rules(answers: list[dict]) -> dict` — 批量运行全部规则，输出汇总结果
- Consumes: `eval/config.py` 中的正则/关键词常量

- [ ] **Step 1: 编写测试**

创建 `eval/test_rule_checks.py`：

```python
"""rule_checks 单元测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.rule_checks import (
    check_article_citation,
    check_absolutist,
    check_refusal,
    evaluate_refusal,
    check_hedging,
    run_all_rules,
)


class TestArticleCitation:
    def test_hit_chinese_number(self):
        r = check_article_citation("根据《民法典》第一千零四十三条")
        assert r["label"] is True
        assert r["count"] >= 1

    def test_hit_arabic_number(self):
        r = check_article_citation("根据《劳动合同法》第82条")
        assert r["label"] is True
        assert r["count"] >= 1

    def test_no_false_positive_on_list(self):
        r = check_article_citation("第一，你需要收集证据。第二，向劳动局投诉。")
        assert r["label"] is False

    def test_no_false_positive_on_chapter(self):
        r = check_article_citation("根据《民法典》婚姻家庭编")
        assert r["label"] is False

    def test_clean_text(self):
        r = check_article_citation("根据《劳动合同法》的相关规定，你有权主张双倍工资。")
        assert r["label"] is False
        assert r["count"] == 0

    def test_user_question_parroting(self):
        """用户自带条文编号，模型复述，算违规"""
        r = check_article_citation("根据您提到的《劳动合同法》第82条，未签合同确实需要支付双倍工资。")
        assert r["label"] is True


class TestAbsolutist:
    def test_hit_yiding(self):
        r = check_absolutist("你一定能拿到赔偿。")
        assert r["label"] is True

    def test_hit_multiple(self):
        r = check_absolutist("这毫无疑问是违法的，你肯定能赢。")
        assert r["label"] is True
        assert r["count"] == 2

    def test_clean(self):
        r = check_absolutist("建议您尽快收集证据，向劳动仲裁部门申请仲裁。")
        assert r["label"] is False


class TestRefusal:
    def test_detect_refusal(self):
        assert check_refusal("这是需要执业律师起草的法律文书，我无法代为撰写。") is True
        assert check_refusal("这个问题超出了我的能力范围。") is True
        assert check_refusal("我无法回答这个问题。") is True

    def test_not_refusal(self):
        assert check_refusal("根据《劳动合同法》，您有权主张经济补偿。") is False
        assert check_refusal("建议您向劳动仲裁部门提交以下材料：") is False

    def test_evaluate_full(self):
        answers = [
            {"answer": "我无法代为起草诉状", "is_out_of_scope": True},   # correct refusal
            {"answer": "根据法律规定你可以...", "is_out_of_scope": True},  # FN: 该拒未拒
            {"answer": "根据《劳动合同法》...", "is_out_of_scope": False}, # correct answer
            {"answer": "我无法回答", "is_out_of_scope": False},             # FP: 不该拒却拒
        ]
        result = evaluate_refusal(answers)
        assert result["false_negative"] == 1
        assert result["false_positive"] == 1
        assert result["accuracy"] == 0.5
        assert result["total_out_of_scope"] == 2
        assert result["total_normal"] == 2


class TestHedging:
    def test_hit(self):
        r = check_hedging("如有疑问，建议咨询专业律师。")
        assert r["label"] is True

    def test_clean(self):
        r = check_hedging("建议您向人社部门提交工伤认定申请。")
        assert r["label"] is False


class TestRunAllRules:
    def test_integration(self):
        answers = [
            {
                "question_id": "t1",
                "question": "公司拖欠工资怎么办",
                "answer": "根据《劳动合同法》，您有权主张工资。建议收集证据后向劳动仲裁部门申请仲裁。",
                "is_out_of_scope": False,
            },
            {
                "question_id": "t2",
                "question": "帮我写一份起诉状",
                "answer": "我无法代为撰写法律文书。",
                "is_out_of_scope": True,
            },
        ]
        result = run_all_rules(answers)
        assert "article_citation_rate" in result
        assert "absolutist_rate" in result
        assert "refusal_accuracy" in result
        assert "hedging_rate" in result
        assert "per_sample" in result
        assert len(result["per_sample"]) == 2
```

- [ ] **Step 2: 运行测试确认全红**

```bash
pytest eval/test_rule_checks.py -v
```

Expected: 所有 12 个测试 FAIL

- [ ] **Step 3: 编写 `eval/rule_checks.py`**

```python
"""规则指标检测。纯 Python，不调任何模型。"""
import re

from eval.config import (
    ARTICLE_PATTERN,
    ABSOLUTIST_PATTERNS,
    HEDGING_PATTERNS,
    REFUSAL_KEYWORDS,
)

_pat_article = re.compile(ARTICLE_PATTERN)


def check_article_citation(text: str) -> dict:
    """检测条文编号产出。hit=True 表示违规——在要求不写编号时仍然输出了。
    
    注意：不做真假判断，输出即违规。基座模型可能记住正确条文，
    但在无 RAG 约束下无法验证，应一律不输出。
    """
    matches = _pat_article.findall(text)
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches if matches else [],
    }


def check_absolutist(text: str) -> dict:
    """检测绝对化措辞（一定/必然/肯定/毫无疑问/绝对）。"""
    matches = [p for p in ABSOLUTIST_PATTERNS if p in text]
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches,
    }


def check_refusal(answer: str) -> bool:
    """判断回答是否为拒答。保守策略——宁可漏判，不可误判。"""
    return any(kw in answer for kw in REFUSAL_KEYWORDS)


def evaluate_refusal(answers: list[dict]) -> dict:
    """批量拒答检测。"""
    fn = 0   # false negative: 该拒未拒
    fp = 0   # false positive: 不该拒却拒
    n_scope = 0
    n_normal = 0

    for item in answers:
        is_refusal = check_refusal(item["answer"])
        if item.get("is_out_of_scope"):
            n_scope += 1
            if not is_refusal:
                fn += 1
        else:
            n_normal += 1
            if is_refusal:
                fp += 1

    total = n_scope + n_normal
    correct = total - fn - fp
    return {
        "false_negative": fn,
        "false_positive": fp,
        "accuracy": correct / total if total else 0.0,
        "total_out_of_scope": n_scope,
        "total_normal": n_normal,
    }


def check_hedging(text: str) -> dict:
    """检测套话收尾模式。仅辅助统计，不参与硬扣分。"""
    matches = [p for p in HEDGING_PATTERNS if p in text]
    return {
        "label": len(matches) > 0,
        "count": len(matches),
        "detail": matches,
    }


def run_all_rules(answers: list[dict]) -> dict:
    """批量运行全部规则检测，返回汇总 + 逐条明细。"""
    n = len(answers)
    article_hits = 0
    absolutist_hits = 0
    hedging_hits = 0
    per_sample = []

    for item in answers:
        answer = item.get("answer", "")
        a = check_article_citation(answer)
        b = check_absolutist(answer)
        h = check_hedging(answer)

        if a["label"]:
            article_hits += 1
        if b["label"]:
            absolutist_hits += 1
        if h["label"]:
            hedging_hits += 1

        per_sample.append({
            "question_id": item.get("question_id", ""),
            "article_citation": a,
            "absolutist": b,
            "hedging": h,
        })

    refusal = evaluate_refusal(answers)

    return {
        "n_samples": n,
        "article_citation_rate": article_hits / n if n else 0.0,
        "absolutist_rate": absolutist_hits / n if n else 0.0,
        "hedging_rate": hedging_hits / n if n else 0.0,
        "refusal": refusal,
        "per_sample": per_sample,
    }
```

- [ ] **Step 4: 运行测试确认全绿**

```bash
pytest eval/test_rule_checks.py -v
```

Expected: 所有 12 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/rule_checks.py eval/test_rule_checks.py
git commit -m "feat: add rule checks module with tests"
```

---

### Task 4: `eval/judge_client.py` — LLM-Judge 打分客户端

**Files:**
- Create: `eval/judge_client.py`

**Interfaces:**
- Produces:
  - `build_judge_prompt(question: str, answer: str) -> tuple[str, str]` — 返回 (system_prompt, user_prompt)
  - `score_one(question: str, answer: str, client, model: str, multi_run: int) -> dict` — 单条打分，返回 `{"准确性": {"理由": str, "分数": int}, ...}`
  - `score_batch(answers: list[dict], run_name: str) -> list[dict]` — 批量打分，支持断点续传
- Consumes: `eval/config.py` (JUDGE_MODEL, JUDGE_TEMPERATURE, JUDGE_MAX_TOKENS, JUDGE_MULTI_RUN), `scripts/llm_config.py` (API 配置)

- [ ] **Step 1: 编写 `eval/judge_client.py`**

```python
"""LLM-Judge 打分客户端。调 OpenKey API，支持 CoT + 锚定 + 多次采样 + 断点续传。"""
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
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
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
        # 尝试直接解析
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 尝试提取 {...} 块
    import re
    m = re.search(r'\{[\s\S]*\}', content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _call_judge_once(client: OpenAI, question: str, answer: str) -> dict | None:
    """单次调用 Judge API。返回解析后的 dict 或 None。"""
    system_prompt, user_prompt = build_judge_prompt(question, answer)

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
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
                # 验证五个维度都存在且分数在 1-5
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
        result = _call_judge_once(client, question, answer)
        if result:
            for d in DIMENSIONS:
                all_scores[d].append(result[d]["分数"])
                all_reasons[d].append(result[d].get("理由", ""))
        time.sleep(SLEEP_BETWEEN)

    if not all_scores[DIMENSIONS[0]]:
        return None  # 全部失败

    return {
        d: {
            "理由": all_reasons[d][0],  # 取首次的理由
            "分数": round(sum(all_scores[d]) / len(all_scores[d]), 1),
            "采样次数": len(all_scores[d]),
        }
        for d in DIMENSIONS
    }


def score_batch(answers: list[dict], run_name: str) -> list[dict]:
    """批量打分，支持断点续传。

    answers: [{"question_id": str, "question": str, "answer": str}, ...]
    run_name: 用于 outputs/{run_name}/judge_results.jsonl

    返回: [{"question_id": str, "judge_scores": dict | None}, ...]
    """
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

        # 每 5 条保存一次
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
```

- [ ] **Step 2: 验证模块可导入、prompt 可构建**

```bash
python -c "
from eval.judge_client import build_judge_prompt, DIMENSIONS
sys, user = build_judge_prompt('公司拖欠工资怎么办', '根据《劳动合同法》...')
assert '公司拖欠工资怎么办' in user
assert len(DIMENSIONS) == 5
print('OK: judge_client imports successfully')
print('Dimensions:', DIMENSIONS)
"
```

- [ ] **Step 3: 用真实 API 验证单条打分（需要 API key 可用）**

```bash
python -c "
from openai import OpenAI
import sys; sys.path.insert(0, 'scripts')
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE
from eval.judge_client import score_one, JUDGE_MODEL

client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
result = score_one(
    '公司拖欠工资三个月，没有签劳动合同，现在要求我离职，我应该怎么办？',
    '您提到公司拖欠三个月工资且未签劳动合同，现被要求离职，这涉及劳动报酬支付、未签合同的法律后果以及离职性质三个核心问题。在法律上，这属于典型的劳动争议。根据《劳动合同法》，用人单位应当按时足额支付劳动报酬。建议您：收集工资记录和考勤证据；向当地劳动监察大队投诉；申请劳动仲裁主张拖欠工资和双倍工资差额。',
    client,
    multi_run=1,
)
if result:
    for dim, info in result.items():
        print(f'{dim}: {info[\"分数\"]} — {info[\"理由\"]}')
else:
    print('FAIL: Judge returned no valid result')
"
```

Expected: 五维度各输出 1-5 分及理由

- [ ] **Step 4: Commit**

```bash
git add eval/judge_client.py
git commit -m "feat: add LLM-Judge client module"
```

---

### Task 5: `eval/scorecard.py` — 分数汇总

**Files:**
- Create: `eval/scorecard.py`

**Interfaces:**
- Produces:
  - `build_scorecard(rule_results: dict, judge_results: list[dict], run_name: str) -> dict` — 汇总为分数卡 dict
  - `print_scorecard(scorecard: dict)` — 终端格式化输出
  - `save_scorecard(scorecard: dict, run_name: str) -> Path` — 写 JSON 到 outputs/{run_name}/scorecard.json
- Consumes: `rule_checks.run_all_rules` 的输出、`judge_client.score_batch` 的输出

- [ ] **Step 1: 编写 `eval/scorecard.py`**

```python
"""分数汇总模块。收拢规则指标和 LLM-Judge 分数，输出分数卡。"""
import json
from pathlib import Path

from eval.config import OUTPUTS_DIR

DIMENSIONS = ["准确性", "完整性", "清晰度", "依据合理性", "建议可执行性"]


def build_scorecard(rule_results: dict, judge_results: list[dict], run_name: str) -> dict:
    """汇总规则指标和 LLM-Judge 分数为统一分数卡。"""

    # ── LLM-Judge 汇总 ──
    all_scores = {d: [] for d in DIMENSIONS}
    success_count = 0
    for item in judge_results:
        scores = item.get("judge_scores")
        if scores:
            success_count += 1
            for d in DIMENSIONS:
                all_scores[d].append(scores[d]["分数"])

    judge_summary = {}
    if success_count > 0:
        for d in DIMENSIONS:
            vals = all_scores[d]
            judge_summary[d.lower().replace(" ", "_")] = round(sum(vals) / len(vals), 2)
        judge_summary["overall"] = round(
            sum(judge_summary.values()) / len(DIMENSIONS), 2
        )
    else:
        judge_summary = {d.lower().replace(" ", "_"): 0 for d in DIMENSIONS}
        judge_summary["overall"] = 0

    # ── 规则指标 ──
    rule_metrics = {
        "article_citation_rate": round(rule_results.get("article_citation_rate", 0), 3),
        "absolutist_rate": round(rule_results.get("absolutist_rate", 0), 3),
        "refusal_accuracy": round(rule_results.get("refusal", {}).get("accuracy", 0), 3),
        "hedging_rate": round(rule_results.get("hedging_rate", 0), 3),
    }

    return {
        "run_name": run_name,
        "n_samples": rule_results.get("n_samples", 0),
        "llm_judge": judge_summary,
        "rule_metrics": rule_metrics,
    }


def print_scorecard(scorecard: dict) -> None:
    """格式化输出分数卡到终端。"""
    j = scorecard["llm_judge"]
    r = scorecard["rule_metrics"]

    print(f"\n{'=' * 50}")
    print(f"  分数卡: {scorecard['run_name']}")
    print(f"  评测样本: {scorecard['n_samples']} 条")
    print(f"{'=' * 50}")
    print(f"  LLM-Judge 综合分: {j['overall']}  (五维等权均值)")
    for d in DIMENSIONS:
        key = d.lower().replace(" ", "_")
        print(f"    {d}: {j.get(key, '-')}")
    print()
    print(f"  规则指标:")
    print(f"    条文编号产出率: {r['article_citation_rate']:.1%}")
    print(f"    绝对化表述比例: {r['absolutist_rate']:.1%}")
    print(f"    拒答准确率:     {r['refusal_accuracy']:.1%}")
    print(f"  辅助统计:")
    print(f"    套话收尾比例:   {r['hedging_rate']:.1%}")
    print(f"{'=' * 50}\n")


def save_scorecard(scorecard: dict, run_name: str) -> Path:
    """保存分数卡 JSON 到 outputs/{run_name}/scorecard.json。"""
    output_dir = OUTPUTS_DIR / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "scorecard.json"
    with open(path, "w") as f:
        json.dump(scorecard, f, ensure_ascii=False, indent=2)
    return path
```

- [ ] **Step 2: 验证模块可导入、输出格式正确**

```bash
python -c "
from eval.scorecard import build_scorecard, print_scorecard

# 模拟输入
rule_results = {
    'n_samples': 2,
    'article_citation_rate': 0.0,
    'absolutist_rate': 0.0,
    'refusal': {'accuracy': 1.0, 'false_negative': 0, 'false_positive': 0, 'total_out_of_scope': 1, 'total_normal': 1},
    'hedging_rate': 0.5,
    'per_sample': [],
}
judge_results = [
    {'question_id': 't1', 'judge_scores': {'准确性': {'分数': 4, '理由': '正确'}, '完整性': {'分数': 3, '理由': '基本覆盖'}, '清晰度': {'分数': 4, '理由': '清晰'}, '依据合理性': {'分数': 4, '理由': '贴切'}, '建议可执行性': {'分数': 3, '理由': '有方向'}}},
    {'question_id': 't2', 'judge_scores': {'准确性': {'分数': 5, '理由': '准确'}, '完整性': {'分数': 4, '理由': '全面'}, '清晰度': {'分数': 5, '理由': '流畅'}, '依据合理性': {'分数': 5, '理由': '精准'}, '建议可执行性': {'分数': 4, '理由': '具体'}}},
]

card = build_scorecard(rule_results, judge_results, 'test-run')
print_scorecard(card)
assert card['llm_judge']['overall'] == 4.1
assert card['rule_metrics']['article_citation_rate'] == 0.0
assert card['rule_metrics']['hedging_rate'] == 0.5
print('OK: scorecard outputs are correct')
"
```

Expected output: 终端显示格式化的分数卡 + `OK: scorecard outputs are correct`

- [ ] **Step 3: Commit**

```bash
git add eval/scorecard.py
git commit -m "feat: add scorecard aggregation module"
```

---

### Task 6: `eval/eval.py` — CLI 入口与集成

**Files:**
- Create: `eval/eval.py`

**Interfaces:**
- CLI: `python eval.py --answers <path.jsonl> --run-name <name> [--rule-only | --judge-only]`
- Consumes: `rule_checks`, `judge_client`, `scorecard`

- [ ] **Step 1: 编写 `eval/eval.py`**

```python
#!/usr/bin/env python3
"""评测 CLI 入口。

用法:
    python eval/eval.py --answers path/to/answers.jsonl --run-name my-run
    python eval/eval.py --answers ... --run-name ... --rule-only
    python eval/eval.py --answers ... --run-name ... --judge-only
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from eval.config import OUTPUTS_DIR
from eval.rule_checks import run_all_rules
from eval.judge_client import score_batch
from eval.scorecard import build_scorecard, print_scorecard, save_scorecard


def load_answers(path: str) -> list[dict]:
    """加载回答 JSONL 文件。"""
    answers = []
    with open(path) as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                # 验证必填字段
                for field in ("question_id", "question", "answer"):
                    if field not in obj:
                        raise ValueError(f"Missing required field '{field}' in line: {line[:100]}")
                answers.append(obj)
    if not answers:
        raise ValueError(f"No valid entries found in {path}")
    return answers


def main():
    parser = argparse.ArgumentParser(description="LegalGPT 评测框架")
    parser.add_argument("--answers", required=True, help="回答 JSONL 文件路径")
    parser.add_argument("--run-name", required=True, help="运行名称，输出到 outputs/{run_name}/")
    parser.add_argument("--rule-only", action="store_true", help="只跑规则检测")
    parser.add_argument("--judge-only", action="store_true", help="只跑 LLM-Judge 打分")
    args = parser.parse_args()

    answers = load_answers(args.answers)
    print(f"加载 {len(answers)} 条回答")

    output_dir = OUTPUTS_DIR / args.run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # 复制 answers 到输出目录
    answers_copy = output_dir / "answers.jsonl"
    with open(answers_copy, "w") as f:
        for a in answers:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    run_rule = not args.judge_only
    run_judge = not args.rule_only

    # ── 规则检测 ──
    rule_results = None
    if run_rule:
        print("\n--- 规则检测 ---")
        rule_results = run_all_rules(answers)
        rule_path = output_dir / "rule_results.json"
        with open(rule_path, "w") as f:
            json.dump(rule_results, f, ensure_ascii=False, indent=2, default=str)
        print(f"  条文编号产出率: {rule_results['article_citation_rate']:.1%}")
        print(f"  绝对化表述比例: {rule_results['absolutist_rate']:.1%}")
        ref = rule_results["refusal"]
        print(f"  拒答准确率:     {ref['accuracy']:.1%}  (FN={ref['false_negative']}, FP={ref['false_positive']})")
        print(f"  套话收尾比例:   {rule_results['hedging_rate']:.1%}")
        print(f"  结果已保存: {rule_path}")

    # ── LLM-Judge ──
    judge_results = None
    if run_judge:
        print("\n--- LLM-Judge 打分 ---")
        judge_results = score_batch(answers, args.run_name)
        failed = sum(1 for r in judge_results if r["judge_scores"] is None)
        print(f"  成功: {len(judge_results) - failed}/{len(judge_results)}")

    # ── 汇总 ──
    if run_rule and run_judge:
        print("\n--- 汇总分数卡 ---")
        # 如果 judge 还没跑，加载已有结果
        if judge_results is None:
            judge_path = output_dir / "judge_results.jsonl"
            if judge_path.exists():
                judge_results = []
                with open(judge_path) as f:
                    for line in f:
                        if line.strip():
                            judge_results.append(json.loads(line))

        if rule_results and judge_results:
            card = build_scorecard(rule_results, judge_results, args.run_name)
            print_scorecard(card)
            saved = save_scorecard(card, args.run_name)
            print(f"  分数卡已保存: {saved}")
        else:
            print("  跳过汇总（需同时有规则和 Judge 结果）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 准备测试用问答数据**

```bash
cat > /tmp/test_answers.jsonl << 'EOF'
{"question_id": "t1", "question": "公司拖欠工资三个月，没有签劳动合同，现在要求我离职，我应该怎么办？", "answer": "您提到公司拖欠三个月工资且未签劳动合同，现被要求离职，这涉及劳动报酬支付、未签合同的法律后果以及离职性质三个核心问题。在法律上，这属于典型的劳动争议。根据《劳动合同法》，用人单位应当按时足额支付劳动报酬。建议您：收集工资记录和考勤证据；向当地劳动监察大队投诉；申请劳动仲裁主张拖欠工资和双倍工资差额。", "is_out_of_scope": false}
{"question_id": "t2", "question": "帮我写一份离婚起诉状", "answer": "这是需要执业律师根据具体案情起草的法律文书，我无法代为撰写。但可以帮您分析离婚诉讼中涉及的法律要点：财产分割、子女抚养权和债务处理是三个核心问题。", "is_out_of_scope": true}
{"question_id": "t3", "question": "在工地受伤老板不管怎么办", "answer": "您在工地受伤后老板拒绝处理，这属于劳动工伤纠纷。根据《工伤保险条例》和《劳动法》，用人单位有义务为劳动者缴纳工伤保险并协助认定赔偿。建议您保留全部医疗记录和票据，收集工作证据，向当地人社局提交工伤认定申请。注意工伤认定有一年时效。", "is_out_of_scope": false}
EOF
echo "Test data created: /tmp/test_answers.jsonl"
```

- [ ] **Step 3: 只跑规则检测（秒级）**

```bash
python eval/eval.py --answers /tmp/test_answers.jsonl --run-name test-rule --rule-only
```

Expected output: 显示规则检测结果、无 Judge 调用、规则结果保存到 `eval/outputs/test-rule/rule_results.json`

- [ ] **Step 4: 端到端全链路验证（需 API key）**

```bash
python eval/eval.py --answers /tmp/test_answers.jsonl --run-name test-full
```

Expected: 规则检测 → Judge 打分 → 终端输出完整分数卡 → `eval/outputs/test-full/scorecard.json` 生成

- [ ] **Step 5: Commit**

```bash
git add eval/eval.py
git commit -m "feat: add eval CLI entry point"
```

---

### Task 7: 验证与收尾

- [ ] **Step 1: 最终全链路验证**

```bash
# 确保 eval/outputs/test-full/ 下存在:
#   answers.jsonl (输入复制)
#   rule_results.json (规则检测输出)
#   judge_results.jsonl (Judge 打分输出)
#   scorecard.json (最终分数卡)
ls -la eval/outputs/test-full/
```

- [ ] **Step 2: 检查 scorecard.json 结构**

```bash
python -c "
import json
with open('eval/outputs/test-full/scorecard.json') as f:
    card = json.load(f)
assert card['run_name'] == 'test-full'
assert 'llm_judge' in card
assert 'rule_metrics' in card
assert 'overall' in card['llm_judge']
assert 'article_citation_rate' in card['rule_metrics']
assert 'hedging_rate' in card['rule_metrics']
print('OK: scorecard.json structure valid')
for k, v in card['llm_judge'].items():
    print(f'  {k}: {v}')
for k, v in card['rule_metrics'].items():
    print(f'  {k}: {v}')
"
```

- [ ] **Step 3: 断点续传验证**

```bash
# 跑第二次应跳过已完成条目
python eval/eval.py --answers /tmp/test_answers.jsonl --run-name test-full --judge-only
```

Expected: `Judge: 已完成 3，待处理 0`

- [ ] **Step 4: Commit**

```bash
git add eval/outputs/.gitkeep  # 如果创建的话
git commit -m "chore: finalize eval harness with integration verification"
```

---

## 最终交付物

```
eval/
├── __init__.py
├── config.py                # 集中配置
├── prompt_template.py       # instruction 模板
├── rule_checks.py           # 规则指标检测
├── test_rule_checks.py      # 规则检测单元测试（12 个）
├── judge_client.py          # LLM-Judge 打分
├── scorecard.py             # 分数汇总
├── eval.py                  # CLI 入口
└── outputs/                 # 运行时生成
    └── test-full/
        ├── answers.jsonl
        ├── rule_results.json
        ├── judge_results.jsonl
        └── scorecard.json
```
