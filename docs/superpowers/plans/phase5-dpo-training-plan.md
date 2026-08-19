# 阶段五：DPO 训练实施计划

**日期**: 2026-08-09
**关联设计**: [phase5-dpo-training-design.md](../specs/phase5-dpo-training-design.md)
**前置**: Phase 4 SFT v4 完成（准确性 92.5%，审慎度 0.93，拒答 0.13）

---

## Task 1: 修 DPO 扰动脚本

**产出**: `scripts/phase3_data/perturb_dpo.py`（修改）
**验证**: `python scripts/phase3_data/perturb_dpo.py --input data/raw/v0.1/ --output /tmp/dpo_test/`，Level 3 校验通过

### 1.1 修复 INSTRUCTION

第 19-26 行的 full prompt → `"你是一名中国法律专家。"`

- 影响范围：所有 DPO 偏好对的 `instruction` 字段
- 验证：输出文件的 `instruction` 字段全部为 bare prompt

### 1.2 新增 `perturb_p6_refusal`

卡 5 专属：将礼貌拒答替换为"硬答"（该拒答时强行给出答案）。

算法：
- 输入：卡 5 的 chosen（一段礼貌拒答文字，如"抱歉，我无法为您起草法律文书，建议咨询律师..."）
- 输出：rejected（一个简短的法律定义/一般性回答，避开了用户真正的问题）
- 实现：从 DISC-LawLLM 知识 QA 中抽取短定义作为 rejected 模板，按用户问题关键词匹配

### 1.3 多 rejected 支持

卡 2 每条 chosen 生成两个 rejected（P6 过确定 + P4 编造事实）。

改动点：
- `perturb_all()` 中，对 card == 2 的样本：分别跑 `perturb_p6` 和 `perturb_p4`，两个都通过 `check_valid` 则各生成一个偏好对
- 不影响其他卡的处理逻辑

### 1.4 新增卡 6 扰动（可选，默认关闭）

`perturb_p6_knowledge`：将简洁知识定义重写为 4 段式推理（格式污染）。
`perturb_p3_knowledge`：替换条文编号或罪名。

通过 `--include-card6` flag 开启，Round 1 默认不启用。

---

## Task 2: 扩充拒答偏好对

**产出**: `scripts/phase3_data/build_refusal_pairs.py`（新建） + `data/raw/v0.1/card5_refusals_expanded.jsonl`
**验证**: 生成 ≥200 对，每条 chosen ≠ rejected，chosen 含拒答语言

### 2.1 扫描华律网原始数据

- 输入：华律网 raw 数据（Phase 3 清洗前的原始文件）
- 筛选条件：问题包含文书写作/合同审查/具体计算等超出咨询边界的意图，且原始回答过短（<100 字）或为空
- 输出：候选问题列表

### 2.2 生成偏好对

- chosen：人工编写或从模板生成的礼貌拒答（统一风格：先道歉说明能力边界 → 提供替代建议）
- rejected：用 V4 SFT 模型对候选问题推理生成"硬答"
- 验证：rejected 不含拒答语言且长度 ≥ 50 字

---

## Task 3: 构造 Round 1 DPO 偏好对

**产出**: `data/processed/dpo/v0.1/train.jsonl`
**验证**: Level 3 校验通过（rejected ≠ chosen，len(rejected) ≥ 50），各卡数量在预期范围

### 3.1 执行

```bash
# Step 1: 扩充拒答
python scripts/phase3_data/build_refusal_pairs.py

# Step 2: 扰动生成（含多 rejected）
python scripts/phase3_data/perturb_dpo.py \
    --input data/raw/v0.1/ \
    --output data/processed/dpo/v0.1/
```

### 3.2 预期数量

| 卡 | 偏好对 |
|------|:---:|
| 2 (P6+P4 多 rejected) | ~1,400 |
| 5 (P6-Refusal + 华律网扩充) | ~200 |
| 1 (P3) | ~370 |
| 3 (P2 + 天然) | ~130 |
| 4 (P2+P5 + 天然) | ~100 |
| **合计** | **~2,200** |

---

## Task 4: 上传数据 + 注册 LLaMA-Factory

**产出**: 服务器上的 DPO 数据 + 配置文件

### 4.1 上传

- `data/processed/dpo/v0.1/train.jsonl` → 服务器
- `configs/legal_dpo_round1.yaml` → 服务器
- 注册 `legal_dpo_round1` 到 `data/dataset_info.json`

### 4.2 训练配置

```yaml
### model
model_name_or_path: /path/to/legalGPT/models/models/qwen--Qwen2.5-7B-Instruct/snapshots/master
adapter_name_or_path: saves/qwen2.5-7b-legal-sft-full

### method
stage: dpo
do_train: true
finetuning_type: lora
lora_target: q_proj,v_proj
dpo_beta: 0.3             # 消融时改为 0.1 / 0.5
dpo_loss: sigmoid

### dataset
dataset: legal_dpo_round1
template: qwen
cutoff_len: 1536

### output
output_dir: saves/qwen2.5-7b-legal-dpo-round1-beta03

### train
per_device_train_batch_size: 4
gradient_accumulation_steps: 8
learning_rate: 5.0e-5
num_train_epochs: 1.0
lr_scheduler_type: cosine
warmup_ratio: 0.03
bf16: true
```

---

## Task 5: Beta 消融训练（三组）

**产出**: 三组 DPO adapter
**预计时间**: ~1.5h (3 × ~30min)

| 实验 | Beta | 输出目录 |
|------|:---:|------|
| A | 0.1 | `saves/qwen2.5-7b-legal-dpo-round1-beta01` |
| B | 0.3 | `saves/qwen2.5-7b-legal-dpo-round1-beta03` |
| C | 0.5 | `saves/qwen2.5-7b-legal-dpo-round1-beta05` |

每次训练后合并 LoRA，跑推理+评测。

---

## Task 6: 评测 + 选最优 Beta

**产出**: 三组分数卡，确定最终 beta

### 6.1 每组合并 + 推理 + CLI 评测

```bash
llamafactory-cli export --adapter_name_or_path saves/qwen2.5-7b-legal-dpo-round1-beta0X ...
python scripts/phase2_eval/run_baseline_inference.py --model <merged> --eval-set <3 sets>
python eval/cli.py --run-name dpo_beta0X
```

### 6.2 选优标准

| 优先级 | 条件 |
|:---:|------|
| 1 | 审慎度 ≥ 1.5 且 拒答 ≥ 1.5 |
| 2 | 准确性 ≥ 90%（退化 < 2.5%） |
| 3 | 两项都满足时，选审慎度+拒答增益最高的 |

如果三组都无法同时满足①和②→ 分析原因（偏好对质量 / 极端 beta 不合适），调整后重新消融。

---

## Task 7: 决策门

```
最优 beta 满足 审慎度≥1.5 且 拒答≥1.5 且 准确性≥90%？
  ├── 是 → ✅ DPO Round 1 完成。冻结权重。
  │         → 视需要决定是否跑 Round 2（质量兜底）
  └── 否 → 诊断失败模式 → 调整策略重新训练
```

---

## 时间估算

| Task | 内容 | 预计时间 |
|------|------|:---:|
| 1 | 修 perturb_dpo.py | 30min |
| 2 | 扩充拒答偏好对 | 1h |
| 3 | 构造偏好对 | 10min |
| 4 | 上传+配置 | 15min |
| 5 | Beta 消融训练 | 1.5h |
| 6 | 评测+选优 | 1h |
| 7 | 决策门 | 15min |
| **合计** | | **~4.5h** |
