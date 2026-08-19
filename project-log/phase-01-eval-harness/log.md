# 阶段 01 · 评测框架搭建

> 对应 `LegalGPT-postTraing-Spec.md` 3.1（阶段一 / M0 前置）。
> 本文按四部分组织：**1. 实现目标 → 2. 实现方法 → 3. 手动实践 → 4. 重点关注和学习**。

---

## 1. 该阶段实现目标

一句话概括阶段一要交付的能力：

> **用一条命令，把「一份模型回答 JSONL」跑成一张包含规则指标和 LLM-Judge 五维打分的分数卡；规则检测是真的、Judge 是真的（调 OpenKey API），只有评测数据是假的（占位 fixture）。**

### 1.1 范围

| 在阶段一范围内 ✅ | 不在阶段一（留给后续阶段）❌ |
|---|---|
| 评测框架模块化（6 个模块） | 正式评测集 `eval_v1.jsonl`（阶段二） |
| 共享 prompt 模板（与 `generate_hualv_answers.py` 同源） | SFT / DPO 训练数据（阶段三） |
| 规则检测（条文编号产出率 / 绝对化表述 / 拒答检测） | LLaMA-Factory 部署与训练（阶段四） |
| LLM-Judge 打分（CoT + 锚定示例 + 多次采样均值 + 断点续传） | 正式模型权重评估 |
| 分数卡（终端 + JSON 双输出） | AutoDL 云端环境验证（训练阶段前置） |
| 15 个规则检测单元测试 | Judge 校准试点（阶段二 30 条标注） |

### 1.2 交付线（DoD）与达成情况

| # | 交付线 | 状态 |
|---|---|---|
| 1 | `python -m eval.cli` 一条命令，输入回答 JSONL + run-name，输出完整分数卡 | ✅ 达成 |
| 2 | 规则检测纯 Python、零模型依赖、毫秒级跑完 | ✅ 达成（`pytest eval/test_rule_checks.py -v` 15 passed） |
| 3 | Judge 调 OpenKey API 真连真出、断点续传可恢复 | ✅ 达成（`gpt-4o-mini` + 3 次采样均值） |
| 4 | prompt 模板与 `generate_hualv_answers.py:SYSTEM_PROMPT` 逐字一致（assert 验证） | ✅ 达成 |

### 1.3 关键验证记录

**规则检测链路**

- `pytest eval/test_rule_checks.py -v`：**15 passed**，覆盖条文编号命中/误伤/列举/编章/用户复述、绝对化单次/多次/干净文本、拒答检测/漏判/误判/批量汇总、套话命中/干净文本、`run_all_rules` 集成。
- `python -m eval.cli --answers /tmp/test_answers.jsonl --run-name test-final --rule-only`：通过，3 条样本秒级完成，生成 `eval/outputs/test-final/rule_results.json`。

**Judge 链路**

- `build_judge_prompt` 含 1 分锚定示例（刑事诈骗误判）和 5 分锚定示例（工伤完整回答）。
- `_parse_response` 正确处理纯 JSON、文本中嵌入 JSON、垃圾输入三种情况。
- `score_batch` 断点续传：首次跑 3 条，中断后重跑 → `已完成 3，待处理 0`，零重复调用。

**prompt 模板一致性**

```python
from scripts.generate_hualv_answers import SYSTEM_PROMPT
from eval.prompt_template import EVAL_INSTRUCTION
assert SYSTEM_PROMPT == EVAL_INSTRUCTION  # True，逐字一致
```

---

## 2. 实现方法（Superpowers 文档驱动开发）

### 2.1 工作流总览

阶段一全程用 Superpowers 框架，走**规范驱动开发（SDD）**流程：`brainstorming（讨论细节）→ 写设计文档 → 写实现计划 → 子代理 TDD 执行 → 收尾`。

> 触发方式：自然语言触发对应 skill，例如「用 brainstorming skill，帮我把阶段一的实施细节讨论清楚」。

### 2.2 第 1 步 · 触发 brainstorming，敲定阶段一细节

触发 `superpowers:brainstorming`，用苏格拉底式提问逐步收敛模糊目标。本阶段被逼问 / 敲定的关键决策：

1. **阶段一只做评测框架，不碰训练。** 仿照参考文档 slot-extractor：LLaMA-Factory 部署、训练链路空跑、AutoDL 验证全部移至训练阶段（阶段四）之前作为前置步骤。
2. **模型推理与评测打分解耦。** 框架不加载模型，输入为「模型已生成好的回答 JSONL」，不关心回答在哪生成（API / AutoDL / 本地）。后续训出权重，在 AutoDL 上生成回答 → 导出 JSON → 本地评测框架出分数卡。
3. **步骤可独立重跑。** 规则检测（毫秒级）和 Judge 打分（API 调分钟级）中间产物各自落盘。改正则无需重跑 Judge，改 Judge prompt 无需重跑规则。
4. **Judge 模型选型**：GPT-4o-mini 主线（DISC-Law-Eval 用 GPT 家族做 Judge，¥29 三实验总成本），GPT-4.1-nano 备选（¥17，试点对比后切换）。GPT-4o（¥437）和 Haiku 4.5（¥218）因成本过高排除。
5. **"虚构引用检测"→"条文编号产出率"。** 不做真假判断——基座模型可能记住正确条文，但在无 RAG 约束下无法验证，输出即指令违规。
6. **"结构完整性"不设规则指标。** canonical 格式禁止标签词，关键词匹配自相矛盾，交 LLM-Judge「清晰度」维度。
7. **"套话收尾"降级为辅助统计。** 正则分不清「诚实边界声明」和「偷懒甩锅」，仅统计出现比例、不参与硬扣分。
8. **prompt 模板以 `generate_hualv_answers.py` 为唯一事实来源。** spec 2.4.5 中的 instruction 是写文档时简化重写的，已标记待修正。

讨论同时触发了 spec 文档的两处重要修改：新增 1.3.1（为什么训练模型不输出条文编号）和评测指标体系全量更新。

### 2.3 第 2 步 · 写设计文档 → 产出 design.md

讨论收敛后，把结论固化为设计文档：

- 产物：[docs/superpowers/specs/phase1-eval-harness-design.md](../../docs/superpowers/specs/phase1-eval-harness-design.md)
- 内容：背景与范围、6 模块目录结构、每个模块的接口契约与实现细节、Judge prompt 锚定示例、验证方案、设计决策汇总、与后续阶段的接口。
- 关键设计原则：**训练/推理/评测三端 prompt 一致**、**规则指标和 LLM-Judge 不合并**、**`is_out_of_scope` 标签随评测集 JSON 走**。

### 2.4 第 3 步 · 触发 writing-plans → 产出实现计划

设计定稿后，触发 `superpowers:writing-plans`，拆成 7 个 Task：

- 产物：[docs/superpowers/plans/phase1-eval-harness-plan.md](../../docs/superpowers/plans/phase1-eval-harness-plan.md)
- 结构：`config → prompt_template → rule_checks + 测试 → judge_client → scorecard → cli → 验证`，按依赖方向排列。
- 每个 Task 含完整代码 + 验证步骤 + 预期输出。

### 2.5 第 4 步 · 子代理 TDD 执行

用 `superpowers:subagent-driven-development`，每 Task 派一个独立子代理执行：

| Task | 模块 | 模型 | 结果 |
|------|------|------|------|
| 1 | `config.py` | haiku | ✅ |
| 2 | `prompt_template.py` | haiku | ✅ （assert 验证与生成脚本一致） |
| 3 | `rule_checks.py` + 测试 | sonnet | ✅ 15/15 passed（子代理发现拒答关键词 `超出能力` 需要拆成 `超出` 才能匹配「超出了我的能力范围」，自动修复） |
| 4 | `judge_client.py` | sonnet | ✅ JSON 解析三种边界情况全通过 |
| 5 | `scorecard.py` | haiku | ✅ `overall=4.1` 计算正确 |
| 6 | `cli.py` | sonnet | ✅ （发现 `eval.py` 与包名冲突，改为 `cli.py`） |
| 7 | 集成验证 | — | ✅ 全模块导入链 + 端到端规则检测 |

**测试落地**：`eval/test_rule_checks.py` 覆盖 6 个测试类、15 个用例，所有函数（含边界情况）全部 TDD 覆盖。

### 2.6 第 5 步 · 收尾

- 初始化 git + 写 `.gitignore`（排除 `.env`、`data/`、`outputs/`、`__pycache__/`）
- `gh repo create legalGPT --private` 推送到 GitHub
- 写 handoff 报告

---

## 3. 手动实践：3 个可亲手跑的体验实验

> 目的：clone 下来就能亲手验证「规则是真的、Judge 是真的、只有数据是假的」。前两个实验零成本（无 API 调用）；实验 3 需要 OpenKey API key。

### 实验 1 · 跑单元测试（零依赖，最快上手）

**目的**：确认规则检测 15 个测试全绿。

```bash
cd legalGPT
python -m pytest eval/test_rule_checks.py -v
```

**预期**：15 passed。六个测试类：条文编号 6 个（含中文数字命中、阿拉伯数字命中、列举误伤防护、编章误伤防护、干净文本、用户复述算违规）、绝对化 3 个、拒答 3 个（含批量汇总）、套话 2 个、集成 1 个。

### 实验 2 · 端到端跑规则检测（秒级，无需 API）

**目的**：感受「回答 JSONL → 规则检测 → 分数卡」完整链路。

```bash
# 创建测试数据
cat > /tmp/test_answers.jsonl << 'EOF'
{"question_id": "t1", "question": "公司拖欠工资三个月，未签合同，现要求我离职，该怎么办？", "answer": "根据《劳动合同法》，您有权主张拖欠工资和双倍工资差额。建议收集工资记录、考勤证据，向劳动监察大队投诉后申请劳动仲裁。", "is_out_of_scope": false}
{"question_id": "t2", "question": "帮我写一份离婚起诉状", "answer": "这是需要执业律师起草的法律文书，我无法代为撰写。但可以帮您分析涉及的法律要点：财产分割、子女抚养权和债务处理。", "is_out_of_scope": true}
{"question_id": "t3", "question": "我在工地摔伤老板不管怎么办", "answer": "根据《工伤保险条例》第17条，您需要在受伤后一年内向人社局提交工伤认定申请。您一定能拿到赔偿。如有疑问建议咨询专业律师。", "is_out_of_scope": false}
EOF

# 跑规则检测
python -m eval.cli --answers /tmp/test_answers.jsonl --run-name experiment-2 --rule-only
```

**预期**：
- t1：干净回答，三项硬指标全部绿色
- t2：拒答正确识别（`is_out_of_scope=true` + 含「无法代为」），FN=0
- t3：**条文编号命中**（第17条）、**绝对化命中**（一定能）、**套话命中**（建议咨询专业律师）——验证三个检测函数都在真工作
- 结果保存到 `eval/outputs/experiment-2/rule_results.json`

### 实验 3 · LLM-Judge 真连真出（需 OpenKey API key）

**目的**：验证 Judge 能真调 API、出五维分数。

**前置**：`.env` 中配置 `OPENKEY_API_KEY` 和 `OPENKEY_API_BASE`。

```bash
# 用实验 2 的同批数据，跑 Judge 打分
python -m eval.cli --answers /tmp/test_answers.jsonl --run-name experiment-3 --judge-only
```

**预期**：3 条回答逐一打分，每条评 3 次取均值（`JUDGE_MULTI_RUN=3`），结果写入 `eval/outputs/experiment-3/judge_results.jsonl`。每条结果含五维分数 + 理由。

**验证断点续传**：再跑一次同样的命令：
```bash
python -m eval.cli --answers /tmp/test_answers.jsonl --run-name experiment-3 --judge-only
```
**预期**：`Judge (gpt-4o-mini): 已完成 3，待处理 0`，零 API 调用。

### 三实验对照

| 实验 | 调 API | 预期耗时 | 预期结果 |
|------|--------|---------|---------|
| 1 单元测试 | 否 | < 1s | 15 passed |
| 2 规则检测 | 否 | < 1s | 3 样本秒级出结果，t3 三违规全命中 |
| 3 Judge 打分 | 是 | ~30s（3 条 × 3 次采样） | 五维分数 + 理由，断点续传可恢复 |

---

## 4. 重点关注和学习

### 4.1 Superpowers 的使用

阶段一完整走完了 Superpowers 的脑力风暴 → 规范 → 计划 → TDD 执行流程。整个过程不是「vibe coding」——每个模块的设计、每个正则的边界、每个 prompt 的措辞，都经过了苏格拉底式讨论和设计审查。

**给读者的建议**：如果想复刻本项目，建议回退到阶段一起点，用 Superpowers 亲手走一遍。在「和 AI 苏格拉底式讨论 → 写设计 → 写计划 → TDD 执行」的过程中，你会对每一行代码为什么这么写理解得远比直接读成品代码深。**开发方法本身，比最终代码更值得学。**

### 4.2 整个评测框架的运行逻辑

以实验 2 那条命令为例：

```
python -m eval.cli --answers /tmp/test_answers.jsonl --run-name experiment-2 --rule-only
```

**数据流**：

```text
load_answers(jsonl)
  │  验证必填字段 (question_id, question, answer)
  │  解析为 list[dict]
  ▼
run_all_rules(answers)
  │  逐条跑 4 个检测函数
  │  check_article_citation / check_absolutist / check_refusal / check_hedging
  │  汇总: article_citation_rate, absolutist_rate, refusal accuracy, hedging_rate
  ▼
  rule_results.json 落盘 eval/outputs/{run_name}/
```

如果全跑（不加 `--rule-only`）：

```text
load_answers → run_all_rules ──→ ┐
                                 ├─→ build_scorecard → print_scorecard (终端)
load_answers → score_batch ───→ ┘       │
        (Judge API,               scorecard.json 落盘
         断点续传,
         多采样均值)
```

**四个贯穿全链路的契约**：

| 契约 | 定义 | 生产者 | 消费者 |
|------|------|--------|--------|
| 回答 JSONL 行 | `{question_id, question, answer, is_out_of_scope?}` | 评测集制作 / 模型推理 | `load_answers` → 全部模块 |
| 规则结果 dict | `{n_samples, article_citation_rate, absolutist_rate, refusal: {accuracy, fn, fp}, hedging_rate, per_sample}` | `rule_checks.run_all_rules` | `scorecard.build_scorecard` |
| Judge 结果 | `[{question_id, judge_scores: {维度: {理由, 分数}}}]` | `judge_client.score_batch` | `scorecard.build_scorecard` |
| 分数卡 dict | `{run_name, n_samples, llm_judge: {overall + 5 dims}, rule_metrics: {4 metrics}}` | `scorecard.build_scorecard` | `scorecard.print_scorecard` / `save_scorecard` |

### 4.3 规则检测的边界思考：为什么这三项是硬指标？

阶段一规则检测只设了三项硬指标（条文编号产出率、绝对化表述比例、拒答准确率），而非更多。选择标准是：

**能确定性判断的才做规则指标。** 条文编号有正则 `第[零一二三四五六七八九十百千0-9]+[条条款项]`——有就是有、没有就是没有。绝对化表述匹配固定词表。拒答关键词匹配。

**不能确定性判断的交给 LLM-Judge。** 结构完整性有歧义——canonical 格式禁止标签词，说明「好的结构」≠「有标签词」，反而「有标签词」=「不好」。正则只能检测标签词的有无，无法判断段落过渡是否自然。套话收尾有歧义——「建议咨询专业律师」在给了具体建议后出现是诚实边界，在空泛回答中出现是偷懒甩锅，纯正则分不清。这些都交给 LLM-Judge。

**设计原则**：规则指标和 LLM-Judge 不合并——前者检测硬性格式/指令违规（量纲是「有没有」），后者评估主观质量（量纲是「好不好」），强行加权掩盖各自信息。

### 4.4 LLM-as-Judge 的一致性保证

这是我们阶段一就认真对待的问题，因为面试一定会被问到。当前落地的措施：

1. **CoT 先行（Judge prompt 要求先给理由再打分）**：强制模型做 claim-level 验证，减少「凭感觉」赋分。HuggingFace 评估指南推荐。
2. **锚定示例（1 分 / 5 分各一条）**：真实法律咨询回答作评分尺度锚点，让 Judge 理解两端边界。
3. **多次采样取均值（每条评 3 次）**：借鉴 Haldar & Hockenmaier (EMNLP 2025) 的研究——即使 temperature=0，不同 run 之间仍可能存在方差，取均值比单次更稳定。
4. **不同实验共用同一 Judge**：base / SFT / SFT+DPO 三组用同一个 Judge、同一份 prompt、同一组锚定示例。即使 Judge 有系统性偏差，跨实验的 delta 仍然有效。核心问题是「SFT 比 base 好吗？」而非「模型得了多少分」。
5. **30 条试点校准（阶段二执行）**：人对 30 条样本打五维分，Judge 也打，计算 Cohen's Kappa（而非原始一致率——Kappa 惩罚碰巧一致）。迭代调 prompt 直到 Kappa > 0.6。**Judge 的一致性本身就是一个实验指标**，会写进 M0 基线报告。

### 4.5 spec 文档的同步修订

阶段一的讨论发现 spec 中多个与实际实现不一致的地方，已全部修正：

| 位置 | 修改 |
|------|------|
| 新增 1.3.1 | 为什么训练模型不输出条文编号 — 四层论证（技术边界 → 安全决策 → 可迁移能力 → Fallback 态） |
| 2.5.3 规则指标 | 虚构引用检测 → 条文编号产出率；移除结构完整性；套话收尾 → 辅助统计 |
| 2.5.4 对比表 | 重排：条文编号产出率 / 绝对化表述比例 / 拒答准确率（硬指标），套话收尾比例（辅助参考） |
| 2.3.5 中断准则 | 结构调整为法律概念命中率 + 清晰度；虚构引用/套话收尾 → 条文编号产出率/绝对化表述/拒答准确率 |
| 2.5 关键前提 | 「惩罚虚构引用」→「惩罚条文编号产出」 |

> 这说明规范文档不是一次写死的——实现过程中会发现矛盾，需要回头修正。设计文档和规范文档的双向同步本身就是工程能力的一部分。

---

## 5. 决策与产物小结

**关键决策**：

- **阶段一只做评测框架，不碰训练**：LLaMA-Factory 部署、训练链路空跑、AutoDL 验证全部移至训练阶段前置。为什么？因为训练之前必须有尺子。评测框架先就绪 → 阶段二造尺子 → 阶段三造数据 → 阶段四才训练——按依赖倒推，不是按难度排列。
- **模型推理与评测打分解耦**：评测框架的输入是回答 JSON，不加载模型。后续 AutoDL 上训出权重 → 生成回答 → 导出 JSON → 本地评测，接口干净。
- **Judge 选型以实验为准**：GPT-4o-mini 主线（有学术先例），GPT-4.1-nano 备选（成本更低），30 条试点对比后最终决定。代码侧两者都支持，改一行配置切换。
- **规则指标只设确定性判断，其余交 LLM-Judge**：正则能确定判的才做硬指标，有歧义的一律降级或委托 Judge。这不是偷懒，是对评测框架的能力边界诚实。
- **指令遵循优于真假判断**：「条文编号产出率」检测的是「模型是否遵循了不写编号的指令」，而非「编号是否正确」——后者我们根本无力判断。

**主要产物**：

- `eval/`：6 个模块的评测框架，15 个单元测试全绿
- `docs/superpowers/specs/phase1-eval-harness-design.md`：完整设计文档
- `docs/superpowers/plans/phase1-eval-harness-plan.md`：7 Task 实现计划
- `docs/handoff/2026-07-21_phase1_eval_harness.md`：阶段完成交接
- spec 修订：1.3.1 新增 + 评测指标体系全量更新
- GitHub：`czc0407/legalGPT`（private）

---

## 6. 2026-08-05 更新：CLI v2 适配新评测体系

Phase 2 评测体系重构后，旧版 `eval/cli.py` 基于五维 Judge + 综合分设计，已不兼容新体系。重写为 v2：

**旧版**（v1）：`--answers` 单文件 → 规则检测 → Judge 五维打分 → 综合分

**新版**（v2）：`--run-name` 前缀 → 自动发现 `eval/outputs/{run}_*.jsonl` → Panel A(规则)→B(Checklist)→C(Quality)→D(Prudence/Refusal) → 生成分数卡

新 CLI 一行命令完成全流程：
```bash
python eval/cli.py --run-name sft --layer1 results/M0_knowledge.json
```

支持 `--panel` 单独跑某个面板，支持断点续传（各子脚本内部）。Scorecard 独立为 `eval/scorecard.py`，也在本次同步重写。
