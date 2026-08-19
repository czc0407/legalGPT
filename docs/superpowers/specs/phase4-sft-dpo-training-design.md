# 阶段四 + 五：SFT 训练 + DPO 训练

**日期**: 2026-08-04（初稿）
**状态**: 设计讨论中
**前置**: Phase 2（评测体系落地）、Phase 3（SFT 数据集 v0.1 冻结）

---

## 1. 背景

### 1.1 前置交付物

| 前置 | 产物 | 说明 |
|------|------|------|
| Phase 2 | 评测体系（4 Panel + 240 条） | 5 维度 + 7 项规则指标 |
| Phase 2 | M0 Baseline | 准确性 77%, 完整性 47%, 审慎度 0.9, 拒答 0.1 |
| Phase 3 | SFT 训练集 7,207 条 | 6 卡混合，canonical 格式 |
| Phase 3 | SFT 验证集 800 条 | 训练期监控用 |

### 1.2 M0 Baseline 关键发现

| 维度 | 基线 | 解读 |
|------|:---:|------|
| R2 法律依据 | 49% | 最大提升空间 |
| R5 覆盖要点 | 54% | 只覆盖一半 |
| 审慎度 | 0.9 | 88% 只做条件分析不追问 |
| 拒答 | 0.1 | 97% 硬答 |

SFT 目标：R2 49%→65%+, R5 54%→65%+, 审慎度 0.9→1.5+，拒答 0.1→1.5+。

---

## 2. 基座模型选型

### 2.1 候选模型

| 模型 | 参数量 | LoRA 显存 | 训练时间 (4090) |
|------|:---:|------|------|
| Qwen2.5-7B-Instruct | 7B | ~18GB | ~8-10h |
| Qwen3-4B-Instruct | 4B | ~12GB | ~4-5h |
| Qwen3-8B-Instruct | 8B | ~22GB | ~12-15h |

### 2.2 选型讨论

- Qwen2.5-7B 是 M0 baseline 所用，结果可直接对比
- Qwen3-4B: 更小，看 LoRA 能否让 4B 接近 7B
- Qwen3-8B: 更新，看代际提升

> **待讨论**：三组全跑？还是只跑 7B（跳过选型，直接用 M0 的 7B）？

---

## 3. SFT 训练配置

### 3.1 超参（main spec 2.3.4）

| 参数 | 值 |
|------|-----|
| Learning rate | 2e-4 |
| Batch size | 32 (4 per device x 8 accumulation) |
| Epochs | 2-3 |
| LR schedule | cosine + 3% warmup |
| Max length | 1,536 |
| LoRA | rank=32, alpha=64, dropout=0.05, target=q_proj+v_proj |
| 硬件 | 单卡 RTX 4090 24GB / 3090 24GB |

### 3.2 数据配置

- 训练集: `data/processed/sft/v0.1/train.jsonl` (7,207条)
- 验证集: `data/processed/sft/v0.1/val.jsonl` (800条)
- 格式: Alpaca `{instruction, input, output}`, `train_on_prompt=false`

### 3.3 监控与中断

| 监控项 | 正常 | 异常处理 |
|------|------|------|
| Train loss | 平稳下降 | 不降/震荡 → 检查数据 |
| Val loss | 同步下降 | 不降反升 → 过拟合 |
| 生成样例 | 每 100 step 抽 3 条 | 退化/重复 → 停训 |
| Layer 1 知识 | accuracy 不降 >5% | 立即停训 |

### 3.4 消融实验

- 半量 (3,600) vs 全量 (7,207) 对比
- 半量先跑（省钱），如果效果已达到预期，全量可跳过

> **待讨论**：先跑半量还是直接全量？

---

## 4. DPO 训练配置（Phase 5）

> **📝 补记：** 本节为 Phase 4 时的初步规划。Phase 5 实际方案（beta 0.5、deepseek-chat 生成 chosen、2019 对偏好对）见 [phase5-dpo-training-design.md](phase5-dpo-training-design.md)。

### 4.1 超参（main spec 2.3.4）

| 参数 | 值 |
|------|-----|
| Learning rate | 5e-5 |
| Beta | 0.3 |
| Epochs | 1 |
| 其余 | 同 SFT |

### 4.2 DPO 数据

- 预估 1,500-2,200 对偏好对
- 双源：从 SFT 数据扰动生成（P2-P6）+ 从 DISC/zixun 保留数据自然提取
- **待 SFT 完成后再生**（扰动策略可根据 SFT 实际结果调整）

---

## 5. 评测计划

每轮训练后跑完整评测套件：

| 步骤 | 内容 |
|------|------|
| 1 | 服务器跑 7B SFT 模型推理（240 条评测集，bare prompt + chat template） |
| 2 | 跑 Checklist (Panel B) + Quality (Panel C) + Prudence/Refusal (Panel D) |
| 3 | 跑 Layer 1 知识保真度（DISC-Law-Eval 2,563 题） |
| 4 | 跑 7 项规则检测 |
| 5 | 生成分数卡，与 M0 Baseline 对比 |

报告格式（main spec 2.5.4）：

| 维度 | M0 Base | M1 SFT | M2 SFT+DPO |
|------|------|------|------|
| 准确性 | 77% | ? | ? |
| 完整性 | 47% | ? | ? |
| 清晰度 | 2.4 | ? | ? |
| 建议可执行性 | 2.4 | ? | ? |
| 审慎度 | 0.9 | ? | ? |
| 拒答 | 0.1 | ? | ? |
| Layer 1 知识 | 29.2% | ? | ? |

---

## 6. 执行环境

SFT 训练需 GPU（训练 3090 服务器已有 7B 模型，可复用），DPO 同理。

当前 3090 服务器：模型 `/path/to/legalGPT/models/models/qwen--Qwen2.5-7B-Instruct/snapshots/master`

需要上传的数据：
- `data/processed/sft/v0.1/train.jsonl`
- `data/processed/sft/v0.1/val.jsonl`

---

## 7. 待讨论项

- [x] 三模型 vs 只跑 7B？→ **先跑 7B，看结果再决定 4B/8B**（最终只跑 7B，未跑 4B/8B——审慎度/拒答的短板是 SFT 方法瓶颈，非换基座能解决）
- [x] 半量 vs 全量？→ **先跑半量（3,600），5h 出结果。效果好则停，不好则补全量**（实际半量 V2/V3、全量 V4 都跑了）
- [x] DPO 扰动策略定否？→ **等 SFT 结果。扰动针对训练后模型的实际弱点设计**
- [x] 训练在 3090 还是租 4090？→ **3090 服务器**
- [x] LLaMA-Factory 版本？→ **用最新稳定版 `pip install llamafactory`，支持 Qwen2.5/Qwen3 + LoRA。Qwen3 需 `enable_thinking=False` 关闭内部 think 标签。**

---

## 8. 训练中确定的关键设计决策

初稿只覆盖了"配置层面"的设计（超参/数据/监控）。训练过程中暴露并确定了 4 个影响 SFT 最终形态的设计决策（详细论证见 [phase-04 log](../../project-log/phase-04-sft-training/log.md)）：

| 决策 | 内容 | 为什么 |
|------|------|--------|
| **bare instruction**（V3 起） | 训练 instruction 从 full prompt → `你是一名中国法律专家。`，与评测推理一致 | 训评 prompt 对齐——模型应"从数据本身学"而非"靠 instruction 提示"组织回答 |
| **R2 评测对齐** | Checklist R2 只比法律名称，不比条文编号 | 消除"训练禁止编号 vs 评测以编号满分"的自相矛盾 |
| **R7 删除** | Checklist 从 7 项减为 6 项（R1-R6） | R7"补充要点"与"简洁高效"训练目标冲突，Judge 无法区分有用补充和无关冗余 |
| **卡2 数据修复** | 卡2（信息不足）从 4 条 → 700 条 | `build_sft_raw.py` 默认运行顺序 `[3,4,1]` 漏执行卡2 生成逻辑（Phase 3 遗留 bug） |

> 训练结果（各轮 loss、评测分数卡）见 log，不在设计文档重复。
