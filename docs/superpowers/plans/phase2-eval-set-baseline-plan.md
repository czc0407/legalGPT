# 阶段二：评测集制作 + Baseline（M0）— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 制作并冻结 415 条二维矩阵评测集，校准 Judge 模型（GPT-4o-mini vs GPT-4.1-nano），跑通 Qwen2.5-0.5B 基线并产出 M0 分数卡。

**Architecture:** 四个新脚本 + 一个 HTML 标注工具。`build_eval_set.py` 先超量抽样 550 条 → LLM 分类 → 按矩阵配额降采样为 385 + 30 = 415 条。标注工具在 30 条试点上合并三项标注任务。`calibrate_judge.py` 算 Kappa + Spearman 选 Judge。`run_baseline_inference.py` 用 0.5B 本地推理 415 条。最后阶段一评测框架收尾出分数卡。

**Tech Stack:** Python 3.10+, OpenAI SDK, Transformers (AutoModelForCausalLM), HTML/CSS/JS（单文件标注工具）

## Global Constraints

- 所有新脚本放 `scripts/` 下，标注工具放 `scripts/annotation_tool.html`
- 评测集输出 `eval_v1.jsonl` 放项目根目录（冻结后不再修改）
- 人工标注输出 `human_labels.json`
- 复用 `scripts/taxonomy_config.py`（80→11 映射）、`scripts/llm_config.py`（API 配置）
- 复用 `eval/prompt_template.py`（推理 prompt）、`eval/config.py`（Judge 配置）
- 评测集格式：`{question_id, question, category, scenario_type, is_out_of_scope, legal_concepts, human_scores}`
- 矩阵配额：类型 1/2 各 10 条/类，类型 3/4/5 各 5 条/类，类型 6 共 30 条
- Judge 校准：Cohen's Kappa + Spearman ρ，κ ≥ 0.6 为底线，两者均 < 0.4 则 Judge prompt 需重设计
- 基线模型：Qwen2.5-0.5B-Instruct（本地 Transformers）

---

### Task 1: `scripts/build_eval_set.py` — 评测集抽样与冻结

**Files:**
- Create: `scripts/build_eval_set.py`

**Interfaces:**
- Consumes: `data/raw_data/question_2.json`（华律网清洗池 580,694 条），`scripts/taxonomy_config.py::LABEL_REMAP`（80→11 映射），`scripts/llm_config.py`（DeepSeek API），`eval/prompt_template.py::EVAL_INSTRUCTION`（仅引用，不用于此脚本）
- Produces: `eval_v1.jsonl` — 冻结评测集，格式 `{question_id, question, category, scenario_type, is_out_of_scope, legal_concepts: [], human_scores: null}`

- [ ] **Step 1: 搭建脚本框架 + 11 类映射**

```python
#!/usr/bin/env python3
"""从华律网清洗池制作二维矩阵评测集并冻结为 eval_v1.jsonl。

流程：超量抽样 → LLM 场景分类 → 降采样 → 输出。
"""
import json
import random
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taxonomy_config import LABEL_REMAP
from llm_config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL, MAX_RETRIES, SLEEP_BETWEEN
from openai import OpenAI

INPUT_FILE = "data/raw_data/question_2.json"
OUTPUT_FILE = "eval_v1.jsonl"
RANDOM_SEED = 42

MATRIX_QUOTA = {
    # scenario_type: per_category_count
    1: 10,  # 信息充分
    2: 10,  # 信息不足
    3: 5,   # 复杂案件
    4: 5,   # 法律不确定
    5: 5,   # 用户要求法律依据
}
OVER_SAMPLE = 50        # 每类超量抽样数
TYPE6_COUNT = 30        # 拒答样本数

CATEGORIES = [
    "婚姻家庭与继承", "债权债务与金融", "劳动与工伤", "交通事故",
    "合同与商业", "人身侵权与消费", "房产与土地", "刑事法律",
    "公司企业与知产", "行政与税务", "综合法律服务",
]
```

- [ ] **Step 2: 实现超量抽样函数**

```python
def load_and_group_questions(path: str) -> dict[str, list[dict]]:
    """读取清洗池，按 11 类分组。跳过无法映射 title 的记录。"""
    by_category = defaultdict(list)
    skipped = 0
    with open(path) as f:
        for i, line in enumerate(f):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            title = obj.get("title", "").strip("[]")   # question_2.json 的 title 带括号，需去掉
            if title not in LABEL_REMAP:
                skipped += 1
                continue
            cat = LABEL_REMAP[title]
            by_category[cat].append({
                "question": obj.get("question", obj.get("content", "")),
                "original_title": title,
            })
    print(f"读取 {i+1} 行，分组 {sum(len(v) for v in by_category.values())} 条，"
          f"跳过 {skipped} 条（title 未映射）")
    return by_category


def oversample(by_category: dict, n_per_cat: int, seed: int) -> list[dict]:
    """每类随机抽 n_per_cat 条，不足则全取并打印警告。"""
    random.seed(seed)
    sampled = []
    for cat in CATEGORIES:
        pool = by_category.get(cat, [])
        if len(pool) < n_per_cat:
            print(f"  ⚠ {cat}: 池中仅 {len(pool)} 条，全取")
            taken = pool
        else:
            taken = random.sample(pool, n_per_cat)
        for item in taken:
            item["category"] = cat
        sampled.extend(taken)
    random.shuffle(sampled)
    return sampled
```

- [ ] **Step 3: 实现 LLM 场景分类**

```python
SCENARIO_PROMPT = """请判断以下法律咨询问题属于哪种任务场景，只输出数字（1-5）：

1 = 信息充分：用户提供了完整的案件事实，诉求明确，足以进行初步法律分析
2 = 信息不足：关键事实缺失（如时间、证据、具体关系等），需要用户补充才能准确判断
3 = 复杂案件：同一问题涉及多个法律关系，或事实复杂需要分别分析
4 = 法律不确定：涉及法律灰色地带、地方性政策差异、或罕见法律情形
5 = 用户要求法律依据：用户明确问"违反哪条法律""依据是什么"等

只输出数字，不要解释。

问题：{question}"""


def classify_scenario_batch(questions: list[str], client: OpenAI) -> list[int]:
    """批量调用 DeepSeek 对问题做场景分类。返回 scenario_type 列表 (1-5)。"""
    results = []
    batch_size = 8
    for i in range(0, len(questions), batch_size):
        batch = questions[i:i + batch_size]
        labels = []
        for q in batch:
            prompt = SCENARIO_PROMPT.format(question=q)
            for attempt in range(MAX_RETRIES):
                try:
                    resp = client.chat.completions.create(
                        model=DEEPSEEK_MODEL,
                        messages=[
                            {"role": "system", "content": "你是一个法律咨询分类器。只输出数字1-5。"},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1, max_tokens=10,
                    )
                    content = resp.choices[0].message.content.strip()
                    label = int(content[0]) if content and content[0].isdigit() else 1
                    labels.append(label)
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        labels.append(1)  # fallback
                    else:
                        import time; time.sleep(2)
        results.extend(labels)
        import time; time.sleep(SLEEP_BETWEEN)
    return results
```

- [ ] **Step 4: 实现降采样 + 输出**

```python
def downsample_matrix(sampled: list[dict], scenario_labels: list[int]) -> list[dict]:
    """按矩阵配额从超量样本中降采样。每类每个场景类型截取配额条数。"""
    # 组织: by_category[cat][scenario_type] = list of items
    by_cat_type = defaultdict(lambda: defaultdict(list))
    for item, stype in zip(sampled, scenario_labels):
        item["scenario_type"] = stype
        by_cat_type[item["category"]][stype].append(item)

    selected = []
    selected_ids = set()

    for cat in CATEGORIES:
        for stype, quota in MATRIX_QUOTA.items():
            pool = by_cat_type[cat][stype]
            taken = pool[:quota]
            if len(taken) < quota:
                print(f"  ⚠ {cat} 类型{stype}: 仅 {len(taken)} 条可用（配额 {quota}），需手工补写")
            for item in taken:
                uid = f"{item['category']}|{item['question'][:50]}"
                if uid not in selected_ids:
                    selected_ids.add(uid)
                    selected.append(item)

    return selected


def write_eval_set(selected: list[dict], type6_samples: list[dict], output_path: str):
    """输出冻结评测集。selected 为类型 1-5，type6 为拒答样本。"""
    with open(output_path, "w") as f:
        for i, item in enumerate(selected, 1):
            obj = {
                "question_id": f"eval_{i:04d}",
                "question": item["question"],
                "category": item["category"],
                "scenario_type": item["scenario_type"],
                "is_out_of_scope": False,
                "legal_concepts": [],
                "human_scores": None,
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        # 类型 6 样本
        for j, item in enumerate(type6_samples, len(selected) + 1):
            obj = {
                "question_id": f"eval_{j:04d}",
                "question": item["question"],
                "category": item.get("category", "综合法律服务"),
                "scenario_type": 6,
                "is_out_of_scope": True,
                "legal_concepts": [],
                "human_scores": None,
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"评测集已冻结: {output_path} ({len(selected) + len(type6_samples)} 条)")
```

- [ ] **Step 5: 组装 main + 类型 6 样本占位**

```python
def main():
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)

    # 1. 加载 + 分组
    by_category = load_and_group_questions(INPUT_FILE)

    # 2. 超量抽样
    sampled = oversample(by_category, OVER_SAMPLE, RANDOM_SEED)
    print(f"超量抽样: {len(sampled)} 条")

    # 3. LLM 场景分类
    questions = [item["question"] for item in sampled]
    scenario_labels = classify_scenario_batch(questions, client)
    print(f"场景分类完成")

    # 4. 降采样
    selected = downsample_matrix(sampled, scenario_labels)
    print(f"降采样后: {len(selected)} 条")

    # 5. 类型 6 样本（占位——后续手工填入）
    type6_samples = TYPE6_PLACEHOLDER

    # 6. 输出
    write_eval_set(selected, type6_samples, OUTPUT_FILE)

    # 7. 统计报告
    from collections import Counter
    by_cat = Counter(item["category"] for item in selected)
    by_type = Counter(item["scenario_type"] for item in selected)
    print(f"\n类别分布: {dict(by_cat)}")
    print(f"场景分布: {dict(by_type)}")


TYPE6_PLACEHOLDER = [
    # 手工构造的 30 条拒答样本，启动脚本前替换此列表
    # 格式: {"question": "...", "category": "综合法律服务"}
]
```

- [ ] **Step 6: 验证脚本可运行（不调 API 的干跑模式）**

```bash
cd /Users/chenzichan/Intern/legalGPT && python -c "
from scripts.build_eval_set import load_and_group_questions, oversample, CATEGORIES, OVER_SAMPLE

# 只测试加载和抽样，不调 API
by_category = load_and_group_questions('data/raw_data/question_2.json')
print(f'分组完成: {sum(len(v) for v in by_category.values())} 条')
for cat in CATEGORIES:
    count = len(by_category.get(cat, []))
    print(f'  {cat}: {count} 条')

sampled = oversample(by_category, OVER_SAMPLE, 42)
print(f'超量抽样: {len(sampled)} 条')
by_cat = {}
for item in sampled:
    by_cat[item['category']] = by_cat.get(item['category'], 0) + 1
for cat in sorted(by_cat):
    print(f'  {cat}: {by_cat[cat]}')
"
```

Expected: 输出 580,694 条分组结果和每类 50 条抽样结果。若某类不足 50 条会打印 ⚠。

- [ ] **Step 7: Commit**

```bash
git add scripts/build_eval_set.py
git commit -m "feat: add eval set builder script (2D matrix sampling)"
```

---

### Task 2: `scripts/annotation_tool.html` — 人工标注工具

**Files:**
- Create: `scripts/annotation_tool.html`

**Interfaces:**
- Consumes: `eval_v1.jsonl`（用户手动加载到浏览器）
- Produces: `human_labels.json`（用户手动导出下载）

**标注任务（三项合并）：** 场景类型核验、法律概念核验、五维 Judge 打分。

- [ ] **Step 1: 编写 HTML 标注工具**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LegalGPT 评测集标注工具</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f5f5f5; }

.anchor { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; font-size: 13px; }
.anchor .bad { border-left: 3px solid #e74c3c; padding-left: 8px; margin: 4px 0; }
.anchor .good { border-left: 3px solid #27ae60; padding-left: 8px; margin: 4px 0; }
.anchor summary { cursor: pointer; font-weight: 600; }

.progress-bar { display: flex; align-items: center; gap: 12px; margin: 16px 0; }
.progress-bar progress { flex: 1; height: 8px; }
.progress-bar span { font-size: 14px; white-space: nowrap; }

.card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.card h3 { font-size: 14px; color: #888; margin-bottom: 8px; text-transform: uppercase; }
.card .question { font-size: 16px; line-height: 1.6; margin-bottom: 16px; padding: 12px; background: #f9f9f9; border-radius: 6px; }
.card .answer { font-size: 15px; line-height: 1.8; padding: 12px; background: #f0f7ff; border-radius: 6px; white-space: pre-wrap; }

.dim-group { margin-bottom: 14px; }
.dim-group label { display: block; font-weight: 600; margin-bottom: 4px; font-size: 14px; }
.dim-group .dim-focus { font-size: 12px; color: #888; margin-bottom: 4px; }
.dim-group .scores { display: flex; gap: 8px; }
.dim-group .scores button { width: 40px; height: 32px; border: 1px solid #ccc; border-radius: 4px; background: #fff; cursor: pointer; font-size: 14px; }
.dim-group .scores button.selected { background: #3498db; color: #fff; border-color: #3498db; }
.dim-group input[type=text] { width: 100%; padding: 4px 8px; margin-top: 4px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }

.concepts { margin: 16px 0; }
.concepts .tag { display: inline-flex; align-items: center; gap: 4px; margin: 2px 4px; padding: 4px 10px; border: 1px solid #ddd; border-radius: 14px; font-size: 13px; cursor: pointer; background: #fff; }
.concepts .tag.checked { background: #e8f5e9; border-color: #27ae60; }
.concepts input.add-concept { width: 200px; padding: 4px 8px; border: 1px dashed #ccc; border-radius: 14px; font-size: 13px; margin: 2px 4px; }

.scenario label { margin-right: 16px; font-size: 14px; cursor: pointer; }
.scenario input { margin-right: 4px; }

.controls { display: flex; gap: 8px; margin: 16px 0; flex-wrap: wrap; }
.controls button { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
.controls .btn-prev { background: #eee; }
.controls .btn-next { background: #3498db; color: #fff; }
.controls .btn-save { background: #27ae60; color: #fff; }
.controls .btn-export { background: #e67e22; color: #fff; }
.controls .btn-load { background: #9b59b6; color: #fff; }

.note { font-size: 13px; color: #888; margin-top: 8px; }
</style>
</head>
<body>

<h1>LegalGPT 评测集标注</h1>

<details class="anchor">
  <summary>📋 评分锚定示例（始终可见）</summary>
  <div class="bad"><strong>1分示例（准确性=1）</strong><br>
  问：公司拖欠工资三个月，没有签劳动合同，现在要求我离职，我应该怎么办？<br>
  答：您好，根据相关法律规定，您可以向公安机关报案，要求追究老板的刑事责任。拖欠工资属于诈骗行为，公安机关会立案处理。<br>
  → <b>准确性=1</b>：故意拖欠工资≠刑事诈骗，法律定性完全错误。</div>
  <div class="good"><strong>5分示例（五维全5）</strong><br>
  问：在工地上干活摔伤了，老板不给报工伤也不赔钱，该怎么办？<br>
  答：您在工地受伤后老板拒绝处理，这属于劳动工伤纠纷…根据《工伤保险条例》和《劳动法》…建议您尽快做三件事：保留全部医疗记录和费用票据；收集聊天记录、转账记录、现场照片等工作证据；向当地人社局提交工伤认定申请…注意工伤认定有一年时效，从受伤日起算，请尽快行动。<br>
  → <b>五维全5</b>：推理完整、法律引用准确、建议具体可操作。</div>
</details>

<div class="progress-bar">
  <progress id="progress" value="0" max="30"></progress>
  <span id="progress-text">0 / 30</span>
</div>

<div class="controls">
  <button class="btn-load" onclick="loadFile()">📂 加载 eval_v1.jsonl</button>
  <button class="btn-prev" onclick="prev()">← 上一条</button>
  <button class="btn-next" onclick="next()">下一条 →</button>
  <button class="btn-save" onclick="save()">💾 保存进度</button>
  <button class="btn-export" onclick="exportJSON()">📥 导出 human_labels.json</button>
</div>

<div id="card" class="card"></div>

<script>
const DIMS = ["准确性", "完整性", "清晰度", "依据合理性", "建议可执行性"];
const DIM_FOCUS = {
  "准确性": "法律结论是否站得住脚？",
  "完整性": "是否遗漏了影响用户决策的关键方面？",
  "清晰度": "推理过程是否易懂、自然流畅？（不检查标签词）",
  "依据合理性": "引用的法律是否与案情匹配？（不评估编号）",
  "建议可执行性": "用户看完知道'下一步做什么'吗？",
};

let data = [];       // 所有样本
let idx = 0;         // 当前索引
let labels = {};     // {question_id: {scenario_type, legal_concepts, human_scores, notes}}

// 恢复进度
const saved = localStorage.getItem('legalGPT_labels');
if (saved) { labels = JSON.parse(saved); }

function loadFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.jsonl,.json';
  input.onchange = e => {
    const file = e.target.files[0];
    const reader = new FileReader();
    reader.onload = ev => {
      data = ev.target.result.split('\n').filter(l => l.trim()).map(l => JSON.parse(l));
      // 只加载 30 条试点（前 30 条正常样本，跳过类型 6）
      data = data.filter(d => d.scenario_type !== 6).slice(0, 30);
      document.getElementById('progress').max = data.length;
      idx = 0;
      render();
    };
    reader.readAsText(file);
  };
  input.click();
}

function render() {
  if (!data.length) {
    document.getElementById('card').innerHTML = '<p>请先加载 eval_v1.jsonl</p>';
    return;
  }
  const item = data[idx];
  const qid = item.question_id;
  const lab = labels[qid] || {scenario_type: item.scenario_type, legal_concepts: item.legal_concepts || [], human_scores: {}, notes: ''};

  let conceptsHTML = (lab.legal_concepts || []).map(c =>
    `<span class="tag checked" onclick="this.remove()">${c} ✕</span>`
  ).join('');
  if (item.legal_concepts && item.legal_concepts.length) {
    // LLM 预标注的候选
    item.legal_concepts.forEach(c => {
      if (!(lab.legal_concepts || []).includes(c)) {
        conceptsHTML += `<span class="tag" onclick="addConcept('${c}')">+ ${c}</span>`;
      }
    });
  }

  let dimsHTML = DIMS.map(d => {
    const score = lab.human_scores ? (lab.human_scores[d] || 0) : 0;
    const buttons = [1,2,3,4,5].map(s =>
      `<button class="${s === score ? 'selected' : ''}" onclick="setScore('${d}', ${s})">${s}</button>`
    ).join('');
    const reason = (lab.human_scores && lab.human_scores[d + '_reason']) || '';
    return `<div class="dim-group">
      <label>${d}</label>
      <div class="dim-focus">${DIM_FOCUS[d]}</div>
      <div class="scores">${buttons}</div>
    </div>`;
  }).join('');

  let scenarioHTML = [1,2,3,4,5].map(t => {
    const checked = lab.scenario_type === t ? 'checked' : '';
    const names = ['','信息充分','信息不足','复杂案件','法律不确定','要求法律依据'];
    return `<label><input type="radio" name="scenario" value="${t}" ${checked} onchange="setScenario(${t})">${names[t]}</label>`;
  }).join(' ');

  document.getElementById('card').innerHTML = `
    <h3>[${item.category}] 场景类型: ${['','信息充分','信息不足','复杂案件','法律不确定','要求法律依据'][lab.scenario_type || 0]}</h3>
    <div class="scenario">${scenarioHTML}</div>
    <div class="question"><strong>【用户问题】</strong><br>${item.question}</div>
    <div class="answer"><strong>【模型回答】</strong><br>${item.answer || '（待基线推理后填入）'}</div>
    <strong>法律概念（点击选中/取消）：</strong>
    <div class="concepts">${conceptsHTML}</div>
    <input class="add-concept" placeholder="+ 添加概念" onkeydown="if(event.key==='Enter'){addConcept(this.value);this.value=''}">
    ${dimsHTML}
    <div class="note">备注：<input type="text" value="${lab.notes || ''}" onchange="setNote(this.value)" placeholder="选填：指出最突出的问题"></div>
  `;

  document.getElementById('progress').value = idx + 1;
  document.getElementById('progress-text').textContent = `${idx + 1} / ${data.length}`;
}

function setScore(dim, val) {
  const qid = data[idx].question_id;
  if (!labels[qid]) labels[qid] = {scenario_type: data[idx].scenario_type, legal_concepts: [], human_scores: {}, notes: ''};
  if (!labels[qid].human_scores) labels[qid].human_scores = {};
  labels[qid].human_scores[dim] = val;
  render();
}

function setScenario(t) {
  const qid = data[idx].question_id;
  if (!labels[qid]) labels[qid] = {scenario_type: t, legal_concepts: [], human_scores: {}, notes: ''};
  labels[qid].scenario_type = t;
  render();
}

function addConcept(c) {
  const qid = data[idx].question_id;
  if (!labels[qid]) labels[qid] = {scenario_type: data[idx].scenario_type, legal_concepts: [], human_scores: {}, notes: ''};
  if (!labels[qid].legal_concepts) labels[qid].legal_concepts = [];
  if (!labels[qid].legal_concepts.includes(c)) labels[qid].legal_concepts.push(c);
  render();
}

function setNote(v) {
  const qid = data[idx].question_id;
  if (!labels[qid]) labels[qid] = {scenario_type: data[idx].scenario_type, legal_concepts: [], human_scores: {}, notes: ''};
  labels[qid].notes = v;
}

function prev() { if (idx > 0) { idx--; render(); } }
function next() { if (idx < data.length - 1) { idx++; render(); } }

function save() {
  localStorage.setItem('legalGPT_labels', JSON.stringify(labels));
  const done = Object.keys(labels).length;
  alert(`已保存: ${done} 条标注进度`);
}

function exportJSON() {
  const blob = new Blob([JSON.stringify(labels, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'human_labels.json';
  a.click();
}

// 每 30 秒自动保存
setInterval(save, 30000);
</script>
</body>
</html>
```

- [ ] **Step 2: 验证工具可用**

在浏览器中打开 `scripts/annotation_tool.html`，确认页面渲染正常、锚定示例可见、按钮可点击。无需测试文件。

- [ ] **Step 3: Commit**

```bash
git add scripts/annotation_tool.html
git commit -m "feat: add human annotation tool (HTML single-file)"
```

---

### Task 3: 人工标注 30 条试点

**此 Task 为手动步骤，无脚本。**

- [ ] **Step 1: 生成试点回答**

在标注之前，需要 30 条试点有模型回答可供评分。先用 DeepSeek API 对 30 条试点生成回答：

```bash
cd /Users/chenzichan/Intern/legalGPT && python -c "
import json
with open('eval_v1.jsonl') as f:
    all_data = [json.loads(l) for l in f if l.strip()]

# 取前 30 条正常样本
pilot = [d for d in all_data if d['scenario_type'] != 6][:30]
print(f'试点: {len(pilot)} 条')

# 用 DeepSeek 生成回答（作为标注时的参考）
from openai import OpenAI
import sys, os; sys.path.insert(0, 'scripts')
from llm_config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL
from eval.prompt_template import format_prompt

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)
for item in pilot:
    prompt = format_prompt(item['question'])
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.3, max_tokens=400,
    )
    item['answer'] = resp.choices[0].message.content.strip()

# 保存带回答案的试点文件
with open('pilot_with_answers.jsonl', 'w') as f:
    for item in pilot:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')
print('试点回答已生成: pilot_with_answers.jsonl')
"
```

- [ ] **Step 2: 打开标注工具进行标注**

1. 浏览器打开 `scripts/annotation_tool.html`
2. 点击「加载 eval_v1.jsonl」→ 选择 `pilot_with_answers.jsonl`
3. 逐条完成：场景类型核验 → 法律概念核验 → 五维打分
4. 完成后点击「导出 human_labels.json」

- [ ] **Step 3: 将 human_labels.json 移到项目根目录**

```bash
mv ~/Downloads/human_labels.json /Users/chenzichan/Intern/legalGPT/
```

---

### Task 4: `scripts/calibrate_judge.py` — Judge 校准

**Files:**
- Create: `scripts/calibrate_judge.py`

**Interfaces:**
- Consumes: `human_labels.json`（人工标注），`eval/config.py::JUDGE_MODEL`，`eval/judge_client.py::score_one`
- Produces: 终端输出 Kappa + Spearman 对比表，Judge 选型结论

- [ ] **Step 1: 编写校准脚本**

```python
#!/usr/bin/env python3
"""Judge 校准：对比 GPT-4o-mini vs GPT-4.1-nano vs 人工标注。

用法:
    python scripts/calibrate_judge.py --labels human_labels.json
"""
import json
import sys
import os
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE
from eval.config import JUDGE_MODEL as DEFAULT_MODEL
from eval.judge_client import score_one, DIMENSIONS


def load_labels(path: str) -> dict:
    """加载人工标注 {question_id: {human_scores: {dim: score}, ...}}"""
    with open(path) as f:
        return json.load(f)


def load_pilot_answers(path: str) -> dict:
    """加载试点样本 {question_id: {question, answer, ...}}"""
    with open(path) as f:
        return {json.loads(l)["question_id"]: json.loads(l) for l in f if l.strip()}


def cohen_kappa(judge_scores: list[int], human_scores: list[int]) -> float:
    """计算 Cohen's Kappa。简化版——将 1-5 视为 5 个类别。"""
    n = len(judge_scores)
    if n == 0:
        return 0.0

    # 混淆矩阵
    matrix = defaultdict(lambda: defaultdict(int))
    for j, h in zip(judge_scores, human_scores):
        matrix[j][h] += 1

    # 观察一致率
    po = sum(1 for j, h in zip(judge_scores, human_scores) if j == h) / n

    # 期望一致率
    pe = 0.0
    for label in range(1, 6):
        p_judge = sum(1 for s in judge_scores if s == label) / n
        p_human = sum(1 for s in human_scores if s == label) / n
        pe += p_judge * p_human

    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def spearman_rho(xs: list, ys: list) -> float:
    """计算 Spearman 秩相关系数。"""
    n = len(xs)
    if n < 2:
        return 0.0
    # 排名（平均排名处理并列）
    def rank(vals):
        sorted_pairs = sorted(enumerate(vals), key=lambda x: x[1])
        ranks = [0] * n
        i = 0
        while i < n:
            j = i
            while j < n and sorted_pairs[j][1] == sorted_pairs[i][1]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                ranks[sorted_pairs[k][0]] = avg
            i = j
        return ranks
    rx = rank(xs)
    ry = rank(ys)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - (6 * d2) / (n * (n**2 - 1))


def run_judge(model: str, pilot_data: dict) -> dict:
    """对试点样本用指定 Judge 模型打分。返回 {qid: {dim: score}}"""
    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    results = {}
    print(f"\n--- {model} ---")
    for i, (qid, item) in enumerate(pilot_data.items()):
        scores = score_one(item["question"], item.get("answer", ""), client, model=model, multi_run=3)
        if scores:
            results[qid] = {d: int(scores[d]["分数"]) for d in DIMENSIONS}
        print(f"  [{i+1}/{len(pilot_data)}] {qid}  {'OK' if scores else 'FAIL'}")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="human_labels.json")
    parser.add_argument("--pilot", default="pilot_with_answers.jsonl")
    args = parser.parse_args()

    human = load_labels(args.labels)
    pilot = load_pilot_answers(args.pilot)

    # 只评估试点中有标注的样本
    common_ids = set(human.keys()) & set(pilot.keys())
    print(f"试点: {len(pilot)} 条, 人工标注: {len(human)} 条, 交集: {len(common_ids)} 条")

    # 跑两个 Judge
    judges = {
        "GPT-4o-mini": "gpt-4o-mini",
        "GPT-4.1-nano": "gpt-4.1-nano",
    }

    judge_results = {}
    for name, model in judges.items():
        judge_results[name] = run_judge(model, {qid: pilot[qid] for qid in common_ids})

    # 计算 Kappa + Spearman
    print(f"\n{'='*70}")
    print(f"{'维度':<12} {'Judge':<14} {'Kappa':>8} {'Spearman ρ':>12}")
    print(f"{'-'*70}")

    for dim in DIMENSIONS:
        human_scores = []
        for qid in common_ids:
            hs = human[qid].get("human_scores", {})
            if dim in hs:
                human_scores.append(hs[dim])

        for name in judges:
            js = []
            for qid in common_ids:
                if qid in judge_results[name] and dim in judge_results[name][qid]:
                    js.append(judge_results[name][qid][dim])

            # 对齐长度（取最短）
            n = min(len(human_scores), len(js))
            k = cohen_kappa(js[:n], human_scores[:n])
            s = spearman_rho(js[:n], human_scores[:n])
            print(f"{dim:<12} {name:<14} {k:>8.3f} {s:>12.3f}")

    print(f"{'='*70}")

    # 选型结论
    print("\n选型结论：")
    for name in judges:
        ks = []
        for dim in DIMENSIONS:
            human_scores = [human[qid]["human_scores"].get(dim) for qid in common_ids if qid in human and dim in human[qid].get("human_scores", {})]
            js = [judge_results[name][qid].get(dim) for qid in common_ids if qid in judge_results[name] and dim in judge_results[name][qid]]
            n = min(len(human_scores), len(js))
            ks.append(cohen_kappa(js[:n], human_scores[:n]))
        mean_k = sum(ks) / len(ks) if ks else 0
        print(f"  {name}: 均值 Kappa = {mean_k:.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本可运行（干跑——不调 API 的导入测试）**

```bash
cd /Users/chenzichan/Intern/legalGPT && python -c "
from scripts.calibrate_judge import cohen_kappa, spearman_rho

# 完全一致 → Kappa=1
assert abs(cohen_kappa([1,2,3,4,5], [1,2,3,4,5]) - 1.0) < 0.001
# 完全相反 → Kappa<0
assert cohen_kappa([1,1,1], [5,5,5]) < 0
# Spearman: 完全正相关
assert abs(spearman_rho([1,2,3,4,5], [1,2,3,4,5]) - 1.0) < 0.001
# Spearman: 完全负相关
assert abs(spearman_rho([1,2,3,4,5], [5,4,3,2,1]) + 1.0) < 0.001
print('OK: Kappa and Spearman functions correct')
"
```

- [ ] **Step 3: 人工标注完成后运行校准**

```bash
cd /Users/chenzichan/Intern/legalGPT && python scripts/calibrate_judge.py --labels human_labels.json --pilot pilot_with_answers.jsonl
```

- [ ] **Step 4: Commit**

```bash
git add scripts/calibrate_judge.py
git commit -m "feat: add judge calibration script (Cohen's Kappa + Spearman)"
```

---

### Task 5: `scripts/run_baseline_inference.py` — 基座模型推理

**Files:**
- Create: `scripts/run_baseline_inference.py`

**Interfaces:**
- Consumes: `eval_v1.jsonl`（评测集），`eval/prompt_template.py::format_prompt`
- Produces: `answers_qwen25_0.5b.jsonl` — `{question_id, question, answer, is_out_of_scope}`

- [ ] **Step 1: 编写推理脚本**

```python
#!/usr/bin/env python3
"""基座模型推理脚本。加载模型 → 逐条生成 → 实时写入 JSONL → 支持断点续传。

用法:
    python scripts/run_baseline_inference.py --model Qwen/Qwen2.5-0.5B-Instruct --eval-set eval_v1.jsonl --output answers_baseline.jsonl
"""
import json
import argparse
import sys
import os
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))
from prompt_template import format_prompt


def load_eval_set(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def generate_answer(model, tokenizer, prompt: str, max_new_tokens: int = 512) -> str:
    """生成一条回答。"""
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1536)
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.0,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    # 只取生成部分（去掉 prompt）
    generated = outputs[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--eval-set", default="eval_v1.jsonl")
    parser.add_argument("--output", default="answers_baseline.jsonl")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    eval_data = load_eval_set(args.eval_set)
    print(f"评测集: {len(eval_data)} 条")

    # 断点续传
    done_ids = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    done_ids.add(json.loads(line)["question_id"])
        print(f"已完成: {len(done_ids)} 条")

    pending = [d for d in eval_data if d["question_id"] not in done_ids]
    print(f"待处理: {len(pending)} 条")

    if not pending:
        print("全部完成！")
        return

    # 加载模型
    print(f"加载模型: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.float32,
        device_map=args.device,
        trust_remote_code=True,
    )
    model.eval()

    total = len(pending)
    for i, item in enumerate(pending):
        prompt = format_prompt(item["question"])
        answer = generate_answer(model, tokenizer, prompt)

        out = {
            "question_id": item["question_id"],
            "question": item["question"],
            "answer": answer,
            "is_out_of_scope": item.get("is_out_of_scope", False),
        }

        # 追加写入
        with open(args.output, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

        if (i + 1) % 10 == 0 or i == total - 1:
            elapsed = time.time()
            print(f"  进度: {i+1}/{total} ({(i+1)*100//total}%)  "
                  f"近条均长: {len(answer)}字")

    print(f"推理完成: {args.output}")
    print(f"总条数: {len(done_ids) + len(pending)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本可导入**

```bash
cd /Users/chenzichan/Intern/legalGPT && python -c "
from scripts.run_baseline_inference import load_eval_set, generate_answer
print('OK: imports work')
"
```

- [ ] **Step 3: 下载模型并运行推理（415 条）**

```bash
cd /Users/chenzichan/Intern/legalGPT && python scripts/run_baseline_inference.py \
  --model Qwen/Qwen2.5-0.5B-Instruct \
  --eval-set eval_v1.jsonl \
  --output answers_qwen25_0.5b.jsonl
```

- [ ] **Step 4: Commit**

```bash
git add scripts/run_baseline_inference.py
git commit -m "feat: add baseline inference script (Transformers + checkpoint resume)"
```

---

### Task 6: M0 基线评测 + 收尾

**此 Task 将前 5 个 Task 的产物串联，产出最终 M0 分数卡。**

- [ ] **Step 1: 运行完整评测**

```bash
cd /Users/chenzichan/Intern/legalGPT && python -m eval.cli \
  --answers answers_qwen25_0.5b.jsonl \
  --run-name m0-baseline-0.5b
```

- [ ] **Step 2: 验证分数卡结构**

```bash
cd /Users/chenzichan/Intern/legalGPT && python -c "
import json
with open('eval/outputs/m0-baseline-0.5b/scorecard.json') as f:
    card = json.load(f)
assert card['run_name'] == 'm0-baseline-0.5b'
assert 'llm_judge' in card
assert 'overall' in card['llm_judge']
assert 'rule_metrics' in card
print('OK: M0 scorecard valid')
print(f'  n_samples: {card[\"n_samples\"]}')
print(f'  overall: {card[\"llm_judge\"][\"overall\"]}')
print(f'  article_citation_rate: {card[\"rule_metrics\"][\"article_citation_rate\"]:.3f}')
"
```

- [ ] **Step 3: 更新 project-log**

写入 `project-log/phase-02-eval-baseline/log.md`（仿照阶段一格式）。

- [ ] **Step 4: 更新 handoff**

写入 `docs/handoff/2026-07-22_phase2_eval_baseline.md`。

- [ ] **Step 5: Final commit + push**

```bash
git add -A && git commit -m "docs: complete Phase 2 eval set + M0 baseline" && git push
```

---

## 依赖关系

```
Task 1 (build_eval_set.py) ──── 产出 eval_v1.jsonl
    │
    ├──→ Task 2 (annotation_tool.html) ── 工具就绪
    │         │
    │         └──→ Task 3 (人工标注) ──── 产出 human_labels.json
    │                    │
    │                    └──→ Task 4 (calibrate_judge.py) ── Judge 选型结论
    │
    └──→ Task 5 (run_baseline_inference.py) ── 产出 answers_baseline.jsonl
              │
              └──→ Task 6 (评测 + 收尾) ── M0 分数卡 + project-log + handoff
```

Task 2 不依赖 Task 1 完成（HTML 工具可先做），Task 4 和 Task 5 可以并行（一个调 API 校准，一个本地跑 0.5B）。
