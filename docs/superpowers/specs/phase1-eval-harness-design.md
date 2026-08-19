# 阶段一：评测框架搭建（推理 + 评测流程）— 设计文档

**日期**: 2026-07-21（初稿）；2026-08-16 更新
**状态**: ✅ 已完成（框架 v2，流程架构沿用至今）
**关联文档**: [LegalGPT-postTraing-Spec.md](../../LegalGPT-postTraing-Spec.md) 3.1 节
**实现日志**: [project-log/phase-01-eval-harness/log.md](../../project-log/phase-01-eval-harness/log.md)

---

## 0. 定位与最终形态

### 0.1 定位

仿照参考文档（slot-extractor）阶段一的思路：**只搭评测闭环，不碰训练。** 阶段一交付的是一个"能对模型回答出分数卡"的评测框架，不涉及 LLaMA-Factory 部署、训练链路空跑——这些训练侧工作移至阶段四之前。

### 0.2 最终形态（框架 v2）

**框架的流程架构从头到尾没变，一直沿用。** 阶段二做的是在框架上叠加新的评测体系（4-Panel），而非推翻框架：

```
模型推理（服务器）→ 回答 JSONL → 规则检测 + LLM-Judge → 分数卡
     └── 与评测解耦：框架不加载模型，只认回答 JSONL
```

6 个原始模块**全部保留至今**，只有 4 处演进（详见 §4 决策节点）：

| 模块 | 状态 |
|------|------|
| `config.py` | ✅ 原样 |
| `prompt_template.py` | ⚠️ 演化：三端一致 → bare/full 两态 |
| `rule_checks.py` | ⚠️ 扩充：3 → 7 项 |
| `judge_client.py` | ✅ 保留（CoT+锚定+断点续传的 API 客户端） |
| `scorecard.py` | ⚠️ 重写：适配四面板独立报告 |
| `cli.py`（原 `eval.py`） | ⚠️ 重写：v2 编排四面板 |

新增模块（阶段二）：`judge_checklist.py` / `judge_quality.py` / `judge_prudence.py` / `judge_refusal.py`（四面板 rubric）。

---

## 1. 核心原则

### 1.1 三条原则（初稿确立，沿用至今）

1. **模型推理与评测打分解耦**：评测框架不加载模型。输入是"模型已生成好的回答 JSON"，输出是分数卡。模型回答在何处生成（远程 API、服务器、本地）与评测框架无关
2. **步骤可独立重跑**：规则检测和 LLM-Judge 打分的中间产物落盘，改规则正则或调 Judge prompt 后无需重新推理
3. **规则指标与 LLM-Judge 不合并**：前者检测硬性格式/指令违规（量纲"有没有"），后者评估主观质量（量纲"好不好"），强行加权掩盖各自信息

### 1.2 原第三条的演化（"三端 prompt 一致"）

初稿第三条原则是"训练/推理/评测三端 prompt 一致"——instruction 模板从 `generate_hualv_answers.py` 提取作为唯一事实来源。**这条原则本身没变，但落地形态在阶段二演化为 bare/full 两态**：评测推理用 bare prompt（`你是一名中国法律专家。`），训练数据生成用 full prompt。拆分原因（阶段二 M0 暴露）见阶段二设计文档 §8.2。

---

## 2. 目录结构（演进标注）

初稿的 6 模块骨架，加上阶段二叠加的模块：

```
eval/
├── config.py               # 集中配置（Judge 模型、阈值）
├── prompt_template.py      # bare(评测) / full(训练) 两态 instruction  ← 演化
├── rule_checks.py          # 规则指标检测（不调模型）7 项  ← 扩充
├── judge_client.py         # LLM-Judge 打分客户端（API 封装，断点续传） ← 保留
├── judge_checklist.py      # Panel B：准确性/完整性  ← 阶段二新增
├── judge_quality.py        # Panel C：清晰度/建议可执行性  ← 阶段二新增
├── judge_prudence.py       # Panel D-1：信息审慎度  ← 阶段二新增
├── judge_refusal.py        # Panel D-2：拒答质量  ← 阶段二新增
├── scorecard.py            # 分数汇总（四面板独立报告）  ← 重写
├── cli.py                  # CLI 入口（v2，原 eval.py）  ← 重命名+重写
├── run_baseline_inference.py  # 基座推理（chat template + bare prompt）
└── run_knowledge_eval.py      # Layer 1 知识保真度评测
```

---

## 3. 模块设计（核心内容，多数沿用）

### 3.1 `prompt_template.py`

两态 instruction。初稿是单一 full prompt，阶段二拆分为：

```python
EVAL_INSTRUCTION = "你是一名中国法律专家。"   # 评测推理（bare）

TRAIN_INSTRUCTION = (
    "你是一位专业的中国法律咨询顾问。你的回答需要体现清晰的法律推理过程……"
    # full prompt，含四段式结构、格式要求（200-300字、书名号不写条文编号等）
)
```

**演化原因**：评测要测模型自身能力而非指令执行能力，full prompt 会人为注入格式合规。依据 Dominguez-Olmedo et al. (2024) 与 DISC-LawLLM 的 bare prompt 实践。

### 3.2 `rule_checks.py`（3 → 7 项）

初稿设 3 项硬指标，阶段二扩充到 7 项。核心设计原则不变：**能确定性判断的才做规则指标，歧义交 LLM-Judge。**

保留的 3 项（初稿设计，逻辑不变）：

| 指标 | 检测 |
|------|------|
| 条文编号产出率 | 正则 `第[零一二三四五六七八九十百千0-9]+[条条款项]` |
| 绝对化表述 | 词表 `一定/必然/肯定/毫无疑问/绝对` |
| 拒答检测 | 关键词 + `is_out_of_scope` 标签 |

**设计决策（沿用）**："条文编号产出率"不做真假判断——基座模型可能记住正确条文，但无 RAG 约束下无法验证，输出即违规。这是指令遵循检测，不是编造检测。

阶段二新增 4 项：框架标签词、法律名白名单、元评论（`【注】``此回答`）、追问检测。

### 3.3 `judge_client.py`（API 客户端，保留）

`judge_client.py` 作为 **LLM-Judge 打分客户端**沿用至今——它的职责是对 OpenKey API 的薄封装（批处理 + 断点续传 + JSON 解析三种边界情况），与具体打分维度无关。阶段二的 4 个 judge 脚本复用此客户端。

初稿里写在此模块下的**5 维打分 rubric（准确性/完整性/清晰度/依据合理性/建议可执行性，1-5 分）已被 4-Panel 取代**，折叠在 §5。

### 3.4 `scorecard.py`

分数汇总原则不变（规则指标与 LLM-Judge 不合并），输出从"5 维综合分"改为"四面板独立报告"。

### 3.5 `cli.py`（v2）

初稿 `eval.py` → 改名 `cli.py`（避免与包名冲突）→ v2 适配四面板：

```bash
python eval/cli.py --run-name sft --layer1 results/M0_knowledge.json
```

v1（初稿）：`--answers` 单文件 → 规则检测 → Judge 五维打分 → 综合分
v2（现在）：`--run-name` 前缀 → 自动发现 `eval/outputs/{run}_*.jsonl` → Panel A(规则)→B(Checklist)→C(Quality)→D(Prudence/Refusal) → 四面板分数卡

### 3.6 `config.py`

基本沿用。初稿的 `JUDGE_MULTI_RUN=3`（多次采样均值）在阶段二实测后改为**日常单次评测，multi-run 留作 debug**（27 条 3 次采样 85% 完全一致、15% ±1 边界抖动，跨实验均值已平滑单条噪声）。

---

## 4. 决策节点（初稿 → 最终的 4 处演进）

| # | 决策节点 | 初稿 | 最终 | 为什么 | 归属 |
|---|---------|------|------|--------|------|
| 1 | 评测推理 prompt | full（三端一致） | **bare** | full prompt 遮蔽真实能力，评测测的是指令执行而非自身能力 | 阶段二 §8 |
| 2 | 规则指标数量 | 3 项 | **7 项** | 补充元评论/追问/白名单/标签词等确定性违规 | 阶段二 §8.5 |
| 3 | Judge 打分维度 | 5 维盲评（1-5 分） | **4-Panel**（Checklist+质量+审慎+拒答，0-3） | GPT-4o-mini 盲评系统性失效，参考答案是可靠 Judge 前提 | 阶段二 §8 |
| 4 | CLI | `eval.py` 单文件 | `cli.py` v2 四面板编排 | 包名冲突 + 适配新评测体系 | 阶段二 |

> 框架自身的三条原则（解耦 / 可重跑 / 规则与 Judge 不合并）**从头到尾未变**，是本阶段真正的设计成果。上述 4 处演进都发生在阶段二"评测体系重设计"，Phase 1 只负责流程骨架。

---

## 5. 旧设计（折叠：5 维 Judge rubric，已被 4-Panel 取代）

<details>
<summary>点击展开：5 维 Judge 打分 rubric（准确性/完整性/清晰度/依据合理性/建议可执行性，1-5 分）</summary>

初稿在 `judge_client.py` 中定义的 5 维盲评 rubric（含 CoT 先行 + 1 分/5 分锚定示例 + 多次采样均值），已被阶段二的 4-Panel 取代。

**废弃原因**：阶段二 M0 全量评测发现，GPT-4o-mini 对 115 条 full prompt 回答打 43% 满分、0% 低于 3 分；同一份带 15 条【注】自语的垃圾回答，GPT-4o-mini 给 5.0、GPT-4 给 2.0。盲评 Judge 无法区分"格式合规"与"内容正确"——这是 30 条试点校准无法暴露的系统性漏洞。阶段二的解法：准确性/完整性改为 Checklist 对比参考答案，清晰度/建议/审慎改为独立 0-3 量表，四面板独立报告。

注意：废弃的是**打分维度 rubric**，不是 `judge_client.py` 本身——该文件作为 API 客户端（断点续传、JSON 解析）沿用至今。

</details>

---

## 6. 验证方案（沿用）

用 10 条华律网真实问题 + DeepSeek API 生成回答，跑通全链路，确认分数卡能正常输出。不追求分数有意义——只验证链路通。

验证步骤：
1. 写 10 条问题到 `test_questions.json`（含 1 条类型 6 样本）
2. 调 DeepSeek API 生成回答，输出 `test_answers.jsonl`
3. `python eval/cli.py --answers test_answers.jsonl --run-name test-run`
4. 检查终端分数卡 + `outputs/test-run/scorecard.json` 格式正确

阶段一实际还落地了 15 个规则检测单元测试（`pytest eval/test_rule_checks.py`），覆盖条文编号命中/误伤/列举/编章/用户复述、绝对化、拒答、套话等边界。

---

## 7. 与后续阶段的接口（沿用）

- **阶段二（评测集 + Baseline）**：产出冻结评测集（DISC 改写 80 + 概念 50 + 行为 110 = 240 条，含 `is_out_of_scope` 标签），作为阶段一评测框架的第一个正式输入
- **阶段四（SFT 训练）**：训练前将 LLaMA-Factory 部署 + 训练链路空跑作为前置步骤。训练产物在服务器上生成回答 → 导出 JSON → 本地评测框架出分数卡
