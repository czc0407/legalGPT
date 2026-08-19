# 数据管线梳理

**版本**: v1.1
**日期**: 2026-08-13
**关联**: [archiving.md](archiving.md)

本文档梳理数据从原始来源到最终训练集的完整流转，按**执行时间顺序**说明每个脚本的作用、输入输出，以及每个数据产物的来源与去向，标注哪些文件需要保留、哪些可以归档。

---

## 1. 数据流全景

```
【原始数据 raw_data/】           【Phase 1 脚本】              【中间产物】               【最终去向 Phase 3】
─────────────────────────────────────────────────────────────────────────────────────────────────────

DISC-Law-SFT-Pair-QA (90MB) ─┐
                              │
zixun_gpt4.json (3MB) ────────┤
                              ├─ process_data.py ──→ DISC_knowledge_qa.jsonl ───────────→ card6_knowledge
                              │                     DISC_consultation_clean.jsonl ─┐
                              │                     zixun_gpt4_clean.jsonl ────────┤
                              │                     consultation_merged.jsonl ←────┘
                              │                              │
question_2.json (156MB) ─→ clean_hualv_data.py ─→ hualv_question_clean.jsonl ─┐   │
                              │                                                  │   │
                              └─ classify_consultation.py ──→ consultation_labeled.jsonl
                                                                                 │
                                       balance_sft_data.py ──────────────────────┤
                                        │  输入: consultation_labeled + hualv_clean
                                        ├→ consultation_retained.jsonl ──→ card3(DISC改写)/card4(zixun改写)
                                        ├→ hualv_questions_to_label.jsonl ──→ card1/card2(华律网生成)
                                        ├→ consultation_dropped.jsonl (丢弃备查)
                                        └→ sft_balance_plan.json (方案文档)
```

> **关键**：Phase 1 的最终产物是 `consultation_retained.jsonl`（有答案的 DISC+zixun 咨询）和 `hualv_questions_to_label.jsonl`（待生成答案的华律网问题）。这两个文件是 Phase 3 `build_sft_raw.py` 的输入，因此是"活跃引用"，必须保留。

---

## 2. 数据源（`data/raw_data/`）

**源头数据，必须保留。** 所有下游产物理论上都能从这里重新生成。

| 文件 | 大小 | 来源 | 用途 |
|------|:---:|------|------|
| `DISC-Law-SFT-Pair-QA-released.jsonl` | 90MB | DISC 开源数据集 | 知识问答(id 0-15986) + 咨询(id 55808-66421) |
| `question_2.json` | 156MB | 华律网爬取 | 原始问题池（67 万条） |
| `zixun_gpt4.json` | 3MB | zixun 咨询 | 咨询类数据 |

---

## 3. Phase 1 脚本清单（按执行顺序）

### 阶段 0：目录准备

| 顺序 | 脚本 | 作用 |
|:---:|------|------|
| 0 | `reorganize_processed.py` | 一次性重组 `data/processed/` 目录结构（历史遗留：早期脚本输出到 `data/processed/` 根目录，此脚本将其分层归位）。当前脚本已直接输出到正确子目录，此脚本不再需要 |

### 阶段 1：清洗（可并行，免费可复现）

| 顺序 | 脚本 | 输入 → 输出 | 作用 |
|:---:|------|------|------|
| 1a | `process_data.py` | DISC + zixun → `DISC_knowledge_qa.jsonl`、`DISC_consultation_clean.jsonl`、`zixun_gpt4_clean.jsonl`、`consultation_merged.jsonl` | 清洗 DISC 和 zixun 两个咨询源：提取知识问答与咨询、删除拒答/免责回答、删除条文编号、合并两源 |
| 1b | `clean_hualv_data.py` | `question_2.json` → `hualv_question_clean.jsonl` + `hualv_cleaning_report.json` | 清洗华律网：过滤广告词、过短问题，输出清洗统计报告 |

### 阶段 2：LLM 分类标注（需 API）

| 顺序 | 脚本 | 输入 → 输出 | 作用 |
|:---:|------|------|------|
| 2 | `classify_consultation.py` | `consultation_merged.jsonl` → `consultation_labeled.jsonl` | 用 LLM 将咨询数据标注为 11 个法律大类，为平衡采样提供类别分布依据 |

### 阶段 3：分布分析（一次性，可选）

| 顺序 | 脚本 | 输入 → 输出 | 作用 |
|:---:|------|------|------|
| 3 | `export_taxonomy_excel.py` | `consultation_labeled.jsonl` + `question_2.json` → `taxonomy_distribution.xlsx` | 统计三数据源 11 类分布并输出 Excel，用于人工决定平衡方案 |

### 阶段 4：平衡采样（免费）

| 顺序 | 脚本 | 输入 → 输出 | 作用 |
|:---:|------|------|------|
| 4 | `balance_sft_data.py` | `consultation_labeled.jsonl` + `hualv_question_clean.jsonl` → `consultation_retained.jsonl`、`hualv_questions_to_label.jsonl`、`consultation_dropped.jsonl`、`sft_balance_plan.json` | 按华律网真实分布调整数据比例（核心三类 80% + 相邻八类 20%），缺口从华律网抽问题待生成，过剩则降采样 |

### 阶段 5：华律网重分类（需 API）

| 顺序 | 脚本 | 输入 → 输出 | 作用 |
|:---:|------|------|------|
| 5a | `reclassify_hualv_questions.py` | `hualv_questions_to_label.jsonl` → `hualv_questions_relabeled.jsonl` | 用 LLM 修正华律网原始 title 标签错误，并**写回 to_label**（覆盖式） |
| 5b | `reclassify_failed.py` | `hualv_questions_to_label.jsonl`（category_original 为空）→ 补分类 | 对 balance 重跑后 `category_original` 被清空的条目重新分类，加回字段 |

> **设计意图（合理）**：全量对华律网池子（67 万条）做 LLM 重分类成本过高，因此采用「先抽样 → 重分类 → 根据重分类结果补抽样」的迭代策略——先用 balance 把范围缩小到 ~4404 条，再对样本重分类修正标签，最后按修正后的标签调整抽样。
>
> **事实链**（由文件时间戳还原）：`reclassify_hualv_questions.py`（5a）有写回逻辑，会把重分类结果覆盖回 `to_label`。但 `balance_sft_data.py` 之后被重跑（18:24），其抽样逻辑只构造 `{"category", "hualv_title", "question", "area", "hualv_id"}`，**不含 `category_original`**，覆盖 `to_label` 时清空了重分类成果。随后 `reclassify_failed.py`（5b，19:17）补救，对所有 `category_original` 为空的条目重新分类并写回。
>
> **最终状态**：`to_label`（19:20）是最新的重分类结果；`relabeled`（14:24）是 balance 重跑前的过期数据，两者有 842 条抽样差异。
>
> ⚠️ **设计缺陷**：第三步「根据重分类结果补抽样」没有接上第二步的重分类结果。`balance_sft_data.py` 的输入只有 `hualv_question_clean.jsonl`（category_l1 原始标签）和 `consultation_labeled.jsonl`，**完全不读 `relabeled` 或 `to_label`**。因此 balance 重跑时：① 补抽样仍按不可靠的华律网原始标签分桶，没有用 reclassify 修正后的标签；② 覆盖 `to_label` 清掉了 reclassify 成果。正确实现应让 balance 重跑时读入 reclassify 修正后的标签作为抽样依据，而非重新按 category_l1 抽样。

### 废弃脚本

| 脚本 | 废弃原因 |
|------|------|
| `generate_hualv_answers.py` | 早期独立答案生成尝试，被 Phase 3 `build_sft_raw.py` 内置的 API 调用逻辑（`call_api` + 质量检查 + 多卡支持）取代。输出 `hualv_answers_generated_sample.jsonl` 仅 57KB（sample 阶段），未进入最终管线 |

---

## 4. 数据产物清单（按生成顺序）

> **归档原则**：正常流程的中间产物和最终产物**全部保留**，只归档失败尝试、废弃工具及其产物、进度追踪文件和临时文件。详见 [archiving.md](archiving.md)。

### 4.1 保留（正常流程产物）

| 文件 | 大小 | 生成阶段 | 从何而来 | 说明 |
|------|:---:|:---:|------|------|
| `raw_processed/DISC_knowledge_qa.jsonl` | 23MB | 阶段 1a | `process_data.py` | card6 的直接输入（`build_knowledge_qa.py` 读取） |
| `raw_processed/DISC_consultation_clean.jsonl` | 3.5MB | 阶段 1a | `process_data.py` | 正常中间产物（merged 的来源之一） |
| `raw_processed/zixun_gpt4_clean.jsonl` | 1.8MB | 阶段 1a | `process_data.py` | 正常中间产物（merged 的来源之一） |
| `raw_processed/hualv_question_clean.jsonl` | 140MB | 阶段 1b | `clean_hualv_data.py` | balance 抽样池 + 拒答扩充数据源 |
| `labeled/consultation_merged.jsonl` | 4.6MB | 阶段 1a | `process_data.py` | classify 的输入（DISC+zixun 合并结果） |
| `labeled/consultation_labeled.jsonl` | 4.7MB | 阶段 2 | `classify_consultation.py` | balance 的输入（LLM 标注产物） |
| `balanced/consultation_retained.jsonl` | — | 阶段 4 | `balance_sft_data.py` | 卡 3/4 的 chosen 来源 |
| `balanced/hualv_questions_to_label.jsonl` | — | 阶段 4 | `balance_sft_data.py` | 卡 1/2 的问题来源 |
| `balanced/consultation_dropped.jsonl` | — | 阶段 4 | `balance_sft_data.py` | 降采样丢弃备查 |
| `balanced/sft_balance_plan.json` | — | 阶段 4 | `balance_sft_data.py` | 平衡方案文档 |
| `balanced/hualv_questions_relabeled.jsonl` | — | 阶段 5a | `reclassify_hualv_questions.py` | 重分类结果（历史版本，与当前 to_label 有 842 条抽样差异） |
| `reports/hualv_cleaning_report.json` | — | 阶段 1b | `clean_hualv_data.py` | 清洗统计报告 |

### 4.2 归档（失败尝试 + 废弃工具 + 临时 + 进度）

| 文件 | 归档理由 |
|------|------|
| `balanced/hualv_answers_generated_sample.jsonl` | 废弃脚本 `generate_hualv_answers.py` 的产物 |
| `reports/taxonomy_distribution.xlsx` | 废弃脚本 `export_taxonomy_excel.py` 的产物 |
| `balanced/*_progress.json` | 进度追踪文件，无复用价值 |
| `temp/*` | 临时文件（低质量标记、预览、进度等） |

---

## 5. Phase 3 消费映射

`build_sft_raw.py` 如何消费 Phase 1 产物生成最终 card 数据：

| Card | 输入文件 | 处理 | 输出 |
|------|------|------|------|
| 1/2 | `balanced/hualv_questions_to_label.jsonl` | 调 API 生成 canonical 答案 | `card1_2_hualv.jsonl` |
| 3 | `balanced/consultation_retained.jsonl` (source=DISC-Law-SFT) | 保留结论 + 补推理链 | `card3_disc_rewrite.jsonl` |
| 4 | `balanced/consultation_retained.jsonl` (source=zixun_gpt4) | 保留结论 + 去壳 | `card4_zixun_rewrite.jsonl` |
| 5 | —（LLM 参数化生成） | 拒答场景生成 | `card5_refusals.jsonl` |
| 6 | `DISC_knowledge_qa.jsonl` | 直接抽取 | `card6_knowledge.jsonl` |

---

## 6. 复现性分析

归档落地后，按复现层级评估影响：

| 层级 | 内容 | 是否受归档影响 | 说明 |
|------|------|:---:|------|
| **L1 训练复现** | 用现有 sft/dpo train.jsonl 训练 | ✅ 不影响 | train.jsonl 已冻结 |
| **L2 Phase 3 复现** | 重新生成 card 文件 | ✅ 不影响 | build_sft_raw.py 的输入（retained + to_label）均保留 |
| **L3 Phase 1 完整复现** | 从 raw_data 重跑全部 | ✅ 不影响 | 正常流程的中间产物和最终产物**全部保留**（含 LLM 标注产物），仅归档的失败尝试/临时文件不参与复现 |

---

## 7. 归档决策速查

归档文件时，先问三个问题：

1. **是源头数据吗？**（raw_data/）→ 保留
2. **是正常流程的产物吗？**（中间产物 + 最终产物）→ 保留
3. **是失败尝试/废弃工具/临时文件的产物吗？** → 归档

> 完整归档规范见 [archiving.md](archiving.md)。
