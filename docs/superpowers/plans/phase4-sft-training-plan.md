# Phase 4 实施计划：SFT 训练

**日期**: 2026-08-04
**前置**: Phase 3 SFT 数据集 v0.1 冻结（训练 7,207 + 验证 800）
**关联设计**: [phase4-sft-dpo-training-design.md](../specs/phase4-sft-dpo-training-design.md)

---

## Task 1: 环境搭建

**目标**: 3090 服务器安装 LLaMA-Factory，验证与 Qwen2.5-7B-Instruct 兼容。

**步骤**:
1. SSH 到 3090 服务器，conda activate legalgpt
2. `pip install llamafactory`（最新稳定版）
3. 验证: `llamafactory-cli version`
4. 确认 Qwen2.5-7B-Instruct 模型路径可用

**验收**: `llamafactory-cli` 可用，模型路径存在。

**预计**: 10 分钟

---

## Task 2: 数据集上传

**目标**: 将 SFT 数据集上传到服务器。

**步骤**:
1. `scp data/processed/sft/v0.1/train.jsonl` → 服务器
2. 随机抽取 3,600 条生成 `train_half.jsonl`
3. `scp data/processed/sft/v0.1/val.jsonl` → 服务器
4. 确认 JSON 格式正确（`instruction/input/output`）

**验收**: 服务器上 `ls -la` 确认文件存在，`wc -l` 确认条数。

**预计**: 5 分钟

---

## Task 3: 写 LLaMA-Factory SFT YAML 配置

**目标**: 创建 training YAML 文件。

**配置要点**:
- model: Qwen2.5-7B-Instruct 绝对路径
- dataset: train_half.jsonl（3,600条）
- LoRA: rank=32, alpha=64, dropout=0.05, target=q_proj+v_proj
- lr=2e-4, batch=32 (4x8), epochs=2, max_len=1536
- output_dir: `saves/qwen2.5-7b-legal-sft-half`

**验收**: YAML 语法正确，`llamafactory-cli train` 启动不报错。

**预计**: 15 分钟

---

## Task 4: 运行半量 SFT 训练

**目标**: 3,600 条数据跑 2 epoch SFT。

**执行**:
```bash
llamafactory-cli train configs/legal_sft_half.yaml
```

**预计**: ~5 小时（3090）

**监控**:
- 关注 training loss 是否下降
- 关注 val loss 是否同步
- 每 ~100 step 抽 3 条看生成质量

---

## Task 5: SFT 模型评测

**目标**: 对训练好的 LoRA adapter 跑完整评测。

**步骤**:
1. 加载 adapter: `PeftModel.from_pretrained(base, adapter_path)`
2. 跑 240 条评测集推理（bare prompt + chat template）
3. 跑 Panel B（Checklist）+ Panel C（Quality）+ Panel D（Prudence/Refusal）
4. 跑 Layer 1 知识保真度（DISC-Law-Eval 2,563 题）
5. 跑 7 项规则检测
6. 生成 M1 分数卡

**对比基准**: M0 Baseline（准确性 77%, 完整性 47%, 审慎度 0.9, 拒答 0.1）

**验收**: M1 分数卡文件 `results/M1_scorecard.json`

**预计**: 推理 ~45min + Judge ~10min + Layer 1 ~3h

---

## Task 6: 决策门

**目标**: 根据 M1 结果决定下一步。

| M1 结果 | 决策 |
|------|------|
| R2 从 49%→65%+ 且 审慎度 >1.5 且 拒答 >1.5 | ✅ 半量已够，进入 Phase 5 DPO |
| R2 <60% 或 审慎度 <1.2 | 🔄 补全量 7,207 重训 |
| Layer 1 知识下降 >5% | 🚨 停训排查（数据/超参问题） |
| 提升不明显（<3%） | 🔄 检查数据分布，补全量 |

**预计**: 人工判断，5 分钟

---

## Task 7（条件）: 全量 SFT 训练

**触发**: Task 6 决定补全量。

**步骤**: 同 Task 3-4，用 train.jsonl（7,207条）。预计 ~10h。

---

## Task 8（条件）: 其他基座模型

**触发**: Task 6 中 7B 效果好，想知道 4B/8B 表现。

**步骤**: 同 Task 3-5，换模型。预计 4B ~5h + 8B ~15h。

---

## 总时间预算

| 路径 | 时间 |
|------|------|
| 最小路径（Task 1-6） | 搭建 30min + 训练 5h + 评测 4h = **~10h** |
| 全量路径（Task 7） | +10h |
| 三模型路径（Task 8） | +20h |

---

## 风险

| 风险 | 应对 |
|------|------|
| 3090 OOM | 调小 batch (2x16) |
| 训练 loss 不收敛 | 检查数据格式，降低 LR 到 1e-4 |
| 半量效果差 | 分析失败的维度，针对性调整数据比例后重训 |
| Qwen3 不兼容 | 回退到只跑 Qwen2.5-7B |
