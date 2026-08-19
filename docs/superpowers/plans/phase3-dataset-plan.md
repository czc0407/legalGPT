# 阶段三：训练数据集制作（SFT + DPO）— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建全套数据构造管线，生成 ~7,600 条 raw 原始样本，渲染为 SFT（Alpaca）和 DPO（preference 对）格式，经三级质量校验后冻结为 v0.1。

**Architecture:** 7 个模块 + 1 个 CLI 编排 + 3 个已有脚本复用。五张数据规格卡定义数据合同，四个 Prompt 驱动 deepseek-chat 生成。SFT 和 DPO 共用同一份 raw——SFT 纯规则渲染，DPO 程序注入 + 天然原始。最终输出 SFT Alpaca JSONL + DPO preference 对 JSONL + dataset_info.json。

**Tech Stack:** Python 3.9+, OpenAI SDK (deepseek-chat), LLaMA-Factory v0.9.5 Alpaca/ShareGPT 格式

## Execution Gates

```
小样冒烟 (40条)  →  全量生成 (~7,600条)
     ↓                      ↓
  管线可跑通            冻结 v0.1
```

冒烟通过 → 全量生成。全量生成过程中滚动质量检查实时报警（spec §9.5）。数据消融实验（半量 vs 全量）在阶段四训练时执行，不在管线中。

## Global Constraints

- 所有新脚本放 `scripts/` 下
- raw 数据输出：`data/raw/v0.1/{card1..5}.jsonl`
- processed 数据输出：`data/processed/{sft,dpo}/v0.1/`
- 复用 `scripts/llm_config.py`（API 配置，OPENKEY_MODEL=deepseek-chat）
- 复用 `eval_v1.jsonl`（指纹隔离检查的评测集）
- SFT 格式：LLaMA-Factory Alpaca `{instruction, input, output}`
- DPO 格式：LLaMA-Factory Alpaca preference `{instruction, input, chosen, rejected}`
- 训练配置：`train_on_prompt=false`
- 五张卡的数据合同见 spec §2，四个 Prompt 见 spec §3
- 卡 3/4 的原始回答来自 `data/processed/balanced/consultation_retained.jsonl`

---

### Task 1: `scripts/build_sft_raw.py` — 原始数据生成器

**Files:**
- Create: `scripts/build_sft_raw.py`
- Consumes: `data/processed/balanced/hualv_questions_to_label.jsonl`（卡 1+2，4,404 条），`data/processed/balanced/consultation_retained.jsonl`（卡 3+4，3,044 条）
- Produces: `data/raw/v0.1/card1_2_hualv.jsonl`, `data/raw/v0.1/card3_disc_rewrite.jsonl`, `data/raw/v0.1/card4_zixun_rewrite.jsonl`
- Reuses: `scripts/llm_config.py`

**职责**：按 spec §3 的四个 Prompt 组装请求，调 deepseek-chat，逐条生成 raw 答案。支持断点续传和 `--smoke` 冒烟模式。

- [ ] **Step 1: 实现 Prompt A（从零生成，卡 1+2）**

  加载 `hualv_questions_to_label.jsonl`，组装 spec §3 Prompt A 的 system + user（含两条 few-shot），调 deepseek-chat，`max_tokens=500`，`temperature=0.3`。`max_tokens` 宽于篇幅上限（200-450 字），不靠硬截断控篇幅——篇幅合规靠 prompt 字数约束 + 质量门统计超长比例。逐条实时写入 `card1_2_hualv.jsonl`，每条含字段：`id, card, source:"hualv_generated", generator_model, category, dpo_targets, question, answer`。`dpo_targets` 当前留空 `[]`，后续 Task 4 程序注入时根据卡类型自动填充。断点续传：维护 progress JSON，已完成的 `id` 跳过。

- [ ] **Step 2: 实现 Prompt B（DISC 重写，卡 3）**

  加载 `consultation_retained.jsonl`，筛选 `source=="DISC-Law-SFT"` 的 2,696 条。组装 spec §3 Prompt B 的 system + user（含一条 few-shot，`{question}` + `{original_answer}`）。其余同 Step 1。输出 `card3_disc_rewrite.jsonl`，字段比卡 1 多一个 `original_answer`。

- [ ] **Step 3: 实现 Prompt C（zixun 重写，卡 4）**

  加载 `consultation_retained.jsonl`，筛选 `source=="zixun_gpt4"` 的 348 条。组装 spec §3 Prompt C 的 system + user（含一条 few-shot）。其余同 Step 2。输出 `card4_zixun_rewrite.jsonl`。

- [ ] **Step 4: `--smoke` 模式支持**

  `--smoke` 模式下每卡只生成 10 条，覆盖 spec §9.2 的冒烟要求（Prompt A 至少 2 充足+2 不足，Prompt B 覆盖不同类别，Prompt C 随机抽取，Prompt D 覆盖全部 4 种拒答场景）。

- [ ] **Step 5: 进度日志 + 滚动质量检查**

  每 10 条输出一次进度统计（完成数/成功率/近 20 条均长）。全量生成模式下，每累计 50 条对已生成样本自动跑 Level 1 正则检查（条文编号/标签词/绝对化/法律名称），按 spec §9.5 阈值打印 `⚠` 警告，不硬停止。最终输出各卡汇总（总条数/平均篇幅/失败条数/违规率）。

**Verification:**
  - `python scripts/build_sft_raw.py --smoke` 产出 30 条 raw（Prompt A/B/C 各 10 条，覆盖卡 1-4）
  - 肉眼抽查 3 条（每个 Prompt 1 条）确认推理链完整、格式合规
  - 手动跑 Level 1 校验确认零硬伤

---

### Task 2: `scripts/build_refusals.py` — 拒答样本生成器

**Files:**
- Create: `scripts/build_refusals.py`
- Produces: `data/raw/v0.1/card5_refusals.jsonl`

**职责**：按 Prompt D 参数化生成约 100 条拒答样本。预置场景变体到 `refusal_scenarios` dict，遍历每个变体调 deepseek-chat。`scenario_type` 参数化、`user_input` 参数化。

- [ ] **Step 1: 定义场景参数池**

  ```python
  REFUSAL_SCENARIOS = [
      # 场景 A: 文书起草
      {"scenario_type": "文书起草", "user_input": "帮我写一份离婚起诉状"},
      {"scenario_type": "文书起草", "user_input": "帮我写一份劳动仲裁申请书"},
      # ... 每种子场景 4-5 个变体
  ]
  ```
  覆盖 spec §3 Prompt D 的四种场景（A 文书起草 / B 实时查询 / C 执业资质 / D 完全无关），每种子场景 4-5 个变体，共约 25 个参数组合。每个组合调用 3-5 次生成不同措辞。

- [ ] **Step 2: 组装 Prompt D 并生成**

  组装 spec §3 Prompt D 的 system + user（`{scenario_type}` + `{user_input}`），调 deepseek-chat。输出 `card5_refusals.jsonl`，字段：`id, card:5, scenario_type:6, source:"llm_generated_refusal", generator_model, category, dpo_targets:["P6"], refusal_subtype, question, answer`。

- [ ] **Step 3: 措辞多样性检查**

  生成完成后，对 100 条 answer 跑 TF-IDF + cosine similarity。相似度 > 0.9 的对标记为「需改写」，调 LLM 重新生成其中一条。重检直到无 > 0.9 对。

**Verification:**
  - 生成 10 条（`--smoke`）验证 pipeline 可跑通（与 spec §9.2 一致：Prompt D 10 条冒烟）
  - 多样性检查通过（0 对 > 0.9，10 条样本足以验证 Pipeline 机制）
  - 肉眼过 3 条确认礼貌拒答 + 零硬伤

---

### Task 3: `scripts/validate_raw.py` — 原始数据校验器

**Files:**
- Create: `scripts/validate_raw.py`
- Consumes: `data/raw/v0.1/*.jsonl`
- Produces: `data/raw/v0.1/validation_report.json`

**职责**：对所有 raw 样本跑 Level 1 校验（spec §5）。逐条检查 + 汇总报告。可修复项自动修复，不可修复项标记并计数。

- [ ] **Step 1: 实现逐条检查函数 `validate_one(record) -> list[Violation]`**

  按 spec §5 Level 1 的检查表逐项实现：
  - 篇幅 < 150 → 重写；> 500 → 统计超长比例交人工决定（不自动截断）
  - 正则检条文编号：`第[零一二三四五六七八九十百千\d]+条`
  - 正则检框架标签词：连续 ≥ 2 个"首先/其次/最后"
  - 正则检绝对化：`[一肯必绝]定[能会要]?|毫无[疑异]问|必然`
  - 法律名称白名单检查（加载 `legal_name_whitelist.json`，区分 a/b/c 三类）
  - NER 案情编造检测：用 `jieba` + 正则提取人名/金额/时间/地点，与 question 交叉比对
  - 卡 3/4 专属：提取重写后法律名称，与 original_answer 比对

- [ ] **Step 2: 实现自动修复函数 `auto_fix(record, violations)`**

  可修复项：删条文编号、删框架标签词、替换绝对化措辞为条件化、替换 c 类法律名称为"根据相关法律规定"。修复后重检。

- [ ] **Step 3: PPL 异常检测**

  用 Qwen2.5-0.5B 本地加载，逐条计算每条 answer 的困惑度（`model(input_ids, labels=input_ids).loss` → PPL = `exp(loss)`）。计算全量 PPL 的均值和标准差，标记 > 均值 + 3σ 的样本。输出 `ppl_outliers.jsonl`，含 `id, ppl, 可能的异常类型（截断/漂移/重复）`。仅标记不自动删除。预期异常率 < 2%。

- [ ] **Step 4: 生成校验报告**

  `validation_report.json` 含：总条数、合规率、各类违规分布、自动修复数、需人工处理数、PPL 异常样本数及 top-10。

**Verification:**
  - 对冒烟 40 条跑校验，确认报告生成
  - 故意构造一条含条文编号+标签词+绝对化+假法律名的样本，确认全部检出
  - 故意构造一条中段截断的样本，确认 PPL 检测标记为异常

---

### Task 4: `scripts/render_sft.py` — SFT 渲染器

**Files:**
- Create: `scripts/render_sft.py`
- Consumes: `data/raw/v0.1/card*.jsonl`（已通过校验）
- Produces: `data/processed/sft/v0.1/train.jsonl`

**职责**：raw → Alpaca SFT 格式。纯规则渲染，不调 LLM。五张卡共用 `instruction`（spec §4.1）。

- [ ] **Step 1: 实现渲染函数**

  ```python
  INSTRUCTION = "你是一位专业的中国法律咨询顾问。请针对用户的问题，给出包含推理过程的法律咨询回答。回答应自然包含：理解用户处境 → 法律定性 → 法律依据与说理 → 结论与建议。引用法律名称时使用书名号，不写具体条文编号。不使用'首先/其次/最后'等标签化结构词作为全文框架。在建议部分可以用数字序号列举具体行动步骤。不编造案情细节和精确数据。"

  def render_sft(raw: dict) -> dict:
      return {
          "instruction": INSTRUCTION,
          "input": raw["question"],
          "output": raw["answer"],
      }
  ```

- [ ] **Step 2: 五卡合并渲染**

  遍历所有 `card*.jsonl` → 逐条 render → 写入 `train.jsonl`。Level 2 校验：instruction 固定、input=question 原文、output 非空且 JSON 合法。

**Verification:**
  - 渲染 40 条冒烟样本，确认 Alpaca 格式正确
  - `train_on_prompt=false` 确认 output 段对应 answer

---

### Task 5: `scripts/perturb_dpo.py` — DPO 扰动器

**Files:**
- Create: `scripts/perturb_dpo.py`
- Consumes: `data/raw/v0.1/card*.jsonl`
- Produces: `data/processed/dpo/v0.1/train.jsonl`
- Assets: `scripts/dpo_assets.py`（预置混淆对表、假名池、套话池）

**职责**：按 spec §4.2 的算法，对 raw 样本注入错误生成 rejected。每条 chosen 可派生多条 rejected（每条一个痛点）。天然 DISC/zixun 原始回答直接作为 rejected 来源。

- [ ] **Step 1: 创建 `dpo_assets.py`**

  ```python
  # 混淆对表 (P3-a)
  CONFUSION_PAIRS = {
      "《劳动合同法》": "《合同法》",
      "《工伤保险条例》": "《医疗保险条例》",
      "《民法典》": "《民事诉讼法》",
      "《道路交通安全法》": "《道路运输条例》",
      "《消费者权益保护法》": "《产品质量法》",
  }

  # 假名池 (P3-b)
  FAKE_LAW_NAMES = [
      "《中华人民共和国劳动保障法》",
      "《中华人民共和国交通管理法》",
      "《中华人民共和国消费者权益保障法》",
      "《中华人民共和国工伤赔偿法》",
  ]

  # 套话池 (P5)
  HEDGING_PHRASES = [
      "建议您咨询专业律师，以实际情况为准",
      "具体情况需要根据法律和事实进行综合判断",
      "建议您通过法律途径维护自己的合法权益",
      "可以咨询当地相关部门了解具体情况",
  ]
  ```

- [ ] **Step 2: 实现 P3 扰动器（法律依据幻觉）**

  检测 chosen 中的《XX法/条例》→ 优先查混淆对表 → 命中则 P3-a 替换 → 未命中则随机从假名池抽取 P3-b。替换后 `rejected != chosen` 校验。

- [ ] **Step 3: 实现 P6 扰动器（过度确定性）**

  检测条件化表述（"如果/若/可能/取决于"）→ 改写为绝对结论。追加至少一处"一定/肯定/必然"。允许自相矛盾。

- [ ] **Step 4: 实现 P5 扰动器（建议空泛）**

  检测具体建议段落 → 替换为套话池随机抽取的一条。其余内容不变。

- [ ] **Step 5: 实现 P2 扰动器（格式不规范）**

  检测 ≥ 3 段的回答 → 在段落起头插入"首先/其次/最后"。

- [ ] **Step 6: 实现 P4 扰动器（编造事实）**

  对卡 2 样本（信息不足），在"理解用户处境"段前插入一句同语义域的编造事实。

- [ ] **Step 7: 实现天然 rejected 提取**

  从 `consultation_retained.jsonl` 提取 DISC/zixun 原始回答（`response` 字段），与对应卡 3/4 的 canonical 重写版本配对。DISC → P1+P2，zixun → P2+P5+P6。

- [ ] **Step 8: DPO 格式输出 + Level 3 校验**

  输出格式：
  ```json
  {"instruction": "<INSTRUCTION>", "input": "<question>", "chosen": "<answer>", "rejected": "<perturbed>"}
  ```
  Level 3 校验：chosen=raw answer、rejected 非空且 ≠ chosen、过篇幅检查。

**Verification:**
  - 对 40 条冒烟样本跑扰动，每类 P 各产出至少 1 对
  - 肉眼 confirm rejected 确实比 chosen 差（不是乱码）
  - 天然 DISC rejected 确认是原始简短回答

---

### Task 6: `scripts/check_isolation.py` — 训评隔离检查

**Files:**
- Create: `scripts/check_isolation.py`
- Consumes: `data/processed/sft/v0.1/train.jsonl`, `eval_v1.jsonl`
- Produces: 隔离报告（stdout + JSON）

**职责**：对训练样本和评测集做指纹硬去重（spec §6）。question 字段归一化（去标点、去空格、小写）→ MD5 → 比对。命中即报错退出。

- [ ] **Step 1: 实现 `fingerprint(question: str) -> str`**

  ```python
  import re, hashlib
  def fingerprint(q: str) -> str:
      normalized = re.sub(r'[^\w]', '', q.lower().replace(' ', ''))
      return hashlib.md5(normalized.encode()).hexdigest()
  ```

- [ ] **Step 2: 遍历比对 + 报错**

  构建评测集指纹集合 → 遍历训练样本 → 命中时输出重叠的 question_id 并 `sys.exit(1)`。

**Verification:**
  - 用冒烟 40 条 + eval_v1 跑一次确认零重叠
  - 故意放一条 eval_v1 里的 question 进去，确认报错退出

---

### Task 7: `scripts/finalize_dataset.py` — 切分 + 版本登记

**Files:**
- Create: `scripts/finalize_dataset.py`
- Consumes: `data/processed/{sft,dpo}/v0.1/train.jsonl`
- Produces: `data/processed/{sft,dpo}/v0.1/{train,val}.jsonl`, `dataset_info.json`, 版本卡

**职责**：9:1 分层切分（按 11 类）、生成 LLaMA-Factory `dataset_info.json`、写版本卡。

- [ ] **Step 1: 分层切分**

  按 `category` 字段分层 → 每类 9:1 → 合并为 train/val。val 仅用于训练监控，不等于 eval_v1。

- [ ] **Step 2: 生成 `dataset_info.json`**

  LLaMA-Factory Alpaca 格式注册：
  ```json
  {
    "phase03_sft_v0_1": {
      "file_name": "sft/v0.1/train.jsonl",
      "formatting": "alpaca",
      "columns": {"prompt": "instruction", "query": "input", "response": "output"}
    },
    "phase03_dpo_v0_1": {
      "file_name": "dpo/v0.1/train.jsonl",
      "formatting": "alpaca",
      "ranking": true,
      "columns": {"prompt": "instruction", "query": "input", "chosen": "chosen", "rejected": "rejected"}
    }
  }
  ```

- [ ] **Step 3: 写版本卡**

  `data/raw/v0.1/VERSION` 记录：各卡条数、各类配比、生成脚本 commit hash、deepseek-chat 模型版本、生成日期。

**Verification:**
  - train/val 各 9:1 分层正确（每类 val ≥ 1 条）
  - `dataset_info.json` 可被 LLaMA-Factory 正确解析（Task 8 空跑确认）

---

### Task 8: `scripts/build_dataset.sh` — CLI 编排 + 端到端冒烟

**Files:**
- Create: `scripts/build_dataset.sh`

**职责**：一条命令串起 Task 1→7。支持 `--smoke`（25 条小样）、`--half`（~3,000 条半量验证）、全量三种模式。

- [ ] **Step 1: 编排脚本**

  ```bash
  #!/bin/bash
  MODE=${1:-smoke}  # smoke | full

  echo "=== Phase 3 Dataset Pipeline ==="
  python scripts/build_sft_raw.py --${MODE}
  python scripts/build_refusals.py --${MODE}
  python scripts/validate_raw.py
  python scripts/render_sft.py
  python scripts/perturb_dpo.py
  python scripts/check_isolation.py
  python scripts/finalize_dataset.py
  echo "=== Complete ==="
  ```

- [ ] **Step 2: 端到端冒烟**

  `bash scripts/build_dataset.sh smoke` → 40 条全链路通过 → 输出 train/val + dataset_info.json。

- [ ] **Step 3: 冒烟审核**

  按 spec §9.3 Checklist 逐项检查 40 条：自动检查 + 肉眼抽 8 条。不符合 spec §9.4 通过标准 → 修 prompt 后重跑。

**Verification:**
  - `bash scripts/build_dataset.sh smoke` 零报错全绿
  - DoD 9 项全部通过

---

### 执行顺序与依赖

```
Task 1: build_sft_raw.py ──┬── 并行
Task 2: build_refusals.py ─┘
              │
Task 3: validate_raw.py
              │
Task 4: render_sft.py ──┬── 并行
Task 5: perturb_dpo.py ─┘
              │
Task 6: check_isolation.py
              │
Task 7: finalize_dataset.py
              │
Task 8: build_dataset.sh（端到端冒烟）
```

### 三段验证流程

```
  Task 8 --smoke (40条)
       │  ✅ 冒烟通过
       ▼
  Task 8 --full (~7,600条)
       │  ✅ 全量冻结
       ▼
     project-log/phase-03-dataset/log.md
```
