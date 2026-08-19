# data/ 目录彻底重构 Plan

**日期**: 2026-08-16
**状态**: 待审核
**Checkpoint**: commit `7fd7ca3`（重构前的干净基线，可回滚）

---

## 一、为什么重构

当前 data/ 是"历史演进堆积"而非"设计出来的结构"，三个核心问题：

1. **`raw_data` vs `raw` 名字太像、语义差太远**（原始下载 vs 训练样本）
2. **`processed/` 边界混乱**：既是"加工管线"（raw_processed/labeled/balanced 中间步骤），又是"成品"（sft/dpo train.jsonl），还混了 reports
3. **SFT 管线被拆散**：同一条管线（清洗→标注→平衡→card→train），中间步骤在 `processed/`，card 样本在 `raw/v0.1/`，硬切到两个顶层目录

---

## 二、新目录结构

**核心原则**：按「数据流阶段」分顶层目录，每个阶段内按自然步骤/round 分。

```
data/
├── external/               # 原始下载数据（只读）
│   ├── DISC-Law-SFT-Pair-QA-released.jsonl
│   ├── zixun_gpt4.json
│   └── question_2.json
│
├── sft/                    # SFT 管线（Phase 1-4，按步骤编号）
│   ├── 01_cleaned/         # ①清洗
│   ├── 02_labeled/         # ②标注
│   ├── 03_balanced/        # ③平衡
│   ├── 04_cards/           # ④card 样本（card1-6）
│   └── 05_train/           # ⑤SFT train.jsonl
│
├── dpo/                    # DPO 管线（Phase 5，按 round 分）
│   ├── v0.1/train.jsonl    # Round 1（规则扰动）
│   ├── v0.2/               # Round 2（强模型 chosen + SFT rejected）
│   │   ├── train.jsonl
│   │   └── 中间数据（dpo_pairs、dpo_rejected、card2_prudence_classified 等）
│   ├── v0.3/train.jsonl    # Round 3（只拒答）
│   ├── v0.4/               # Round 4（方案 A）
│   │   ├── train.jsonl
│   │   └── 中间数据（refusal_*_v4、symmetric_*_v4）
│   └── v0.5/               # Round 5（数据重做）
│       ├── train_v1.jsonl / train_v2.jsonl / format.jsonl
│       └── 中间数据（refusal_*_v5、prudence_*_v5）
│
└── reports/                # 清洗/校验报告
```

**改进点**：
- `raw_data` → `external`（消除与 `raw` 的歧义）
- SFT 管线 5 个步骤聚到 `sft/` 下（不再拆散）
- DPO 中间数据 + train.jsonl 按 round 聚到 `dpo/v0.x/`（不再分 raw/dpo 和 processed/dpo 两处）
- `temp/` 删除（空目录）

---

## 三、文件移动映射

| 旧路径 | 新路径 |
|--------|--------|
| `raw_data/*` | `external/*` |
| `processed/raw_processed/*` | `sft/01_cleaned/*` |
| `processed/labeled/*` | `sft/02_labeled/*` |
| `processed/balanced/*` | `sft/03_balanced/*` |
| `raw/v0.1/*`（card1-6 + progress + validation）| `sft/04_cards/*` |
| `processed/sft/v0.1/*` | `sft/05_train/*` |
| `processed/dpo/v0.1/train.jsonl` | `dpo/v0.1/train.jsonl` |
| `processed/dpo/v0.2/*` + `raw/dpo/v0.2/*` | `dpo/v0.2/*` |
| `processed/dpo/v0.3/train.jsonl` | `dpo/v0.3/train.jsonl` |
| `processed/dpo/v0.4/*` + `raw/dpo/v0.4/*` | `dpo/v0.4/*` |
| `processed/dpo/v0.5_format/train.jsonl` | `dpo/v0.5/format/train.jsonl` |
| `processed/dpo/v0.5_v1/train.jsonl` | `dpo/v0.5/v1/train.jsonl` |
| `processed/dpo/v0.5_v2/train.jsonl` | `dpo/v0.5/v2/train.jsonl` |
| `raw/dpo/v0.5/*`（中间数据）| `dpo/v0.5/*` |
| `processed/reports/*` | `reports/*` |
| `processed/temp/` | （删除）|

---

## 四、脚本路径改动

涉及引用 data/ 路径的脚本（约 15 个），路径映射：

| 旧路径片段 | 新路径片段 |
|-----------|-----------|
| `data/raw/v0.1/card` | `data/sft/04_cards/card` |
| `data/raw/v0.1/validation` | `data/sft/04_cards/validation` |
| `data/raw/dpo/v0.2/` | `data/dpo/v0.2/` |
| `data/raw/dpo/v0.4/` | `data/dpo/v0.4/` |
| `data/raw/dpo/v0.5/` | `data/dpo/v0.5/` |
| `data/processed/dpo/v0.1/` | `data/dpo/v0.1/` |
| `data/processed/dpo/v0.2/` | `data/dpo/v0.2/` |
| `data/processed/dpo/v0.3/` | `data/dpo/v0.3/` |
| `data/processed/dpo/v0.4/` | `data/dpo/v0.4/` |
| `data/processed/dpo/v0.5_format/` | `data/dpo/v0.5/format.jsonl` |
| `data/processed/dpo/v0.5_v1/` | `data/dpo/v0.5/train_v1.jsonl` |
| `data/processed/dpo/v0.5_v2/` | `data/dpo/v0.5/train_v2.jsonl` |
| `data/processed/sft/v0.1/` | `data/sft/05_train/` |

受影响脚本：
- `scripts/phase3_data/`：perturb_dpo.py、build_sft_raw.py、build_refusal_pairs.py、render_sft.py、validate_raw.py 等（引用 card/processed 路径）
- `scripts/phase5_dpo/data/`、`generate/`、`score/`：所有数据构造脚本
- `scripts/train/`：推理脚本（数据路径）
- `eval/`：评测集路径（如果引用 data/）

---

## 五、文档更新

| 文件 | 变更 |
|------|------|
| `data/README.md` | 重写为新目录结构 |
| `docs/project-conventions/directory-structure.md` | 更新（或由本 plan 取代）|
| `project-log/phase-05-dpo-training/log.md` | 数据路径引用更新（可选，历史文档）|
| `docs/handoff/` | 数据路径引用更新（可选）|

---

## 六、执行步骤

1. **确认 checkpoint**：`git status` 干净，commit `7fd7ca3` 可回滚
2. **创建新目录骨架**：`mkdir` external/sft/{01_cleaned,02_labeled,03_balanced,04_cards,05_train}/dpo/{v0.1..v0.5}/reports
3. **移动文件**：按 §三 映射表 `mv`（先 `git status` 确认 data 不在 git，用普通 mv）
4. **改脚本路径**：sed 批量替换 §四 的路径映射
5. **改文档**：README + directory-structure.md
6. **验证**：`python -m py_compile` 所有脚本 + 抽查数据文件存在
7. **服务器同步**：服务器上的数据/脚本路径也同步调整（训练时读路径一致）
8. **git commit**：提交重构

---

## 七、风险与回滚

| 风险 | 应对 |
|------|------|
| 移动文件后脚本路径失效 | 步骤 4 批量 sed + 步骤 6 验证 |
| 移动过程误删文件 | 用 `mv`（非 rm），移动前 `ls` 确认源存在；移动后可 `git checkout` 回滚（data 不在 git，需手动回滚）|
| 服务器路径不一致 | 步骤 7 服务器同步；训练前确认 dataset_info.json 路径 |
| 重构后脚本跑不通 | 保留 checkpoint `7fd7ca3`，可 `git reset --hard` 回滚脚本，数据文件手动 mv 回 |

**回滚方案**：脚本回滚用 `git reset --hard 7fd7ca3`；数据文件回滚需手动反向 mv（本 plan §三 映射表反向执行）。

---

## 八、决策（已确认）

1. **数据版本命名**：保持 v0.x（改动最小，版本语义一致）✅
2. **SFT 步骤编号**：带数字前缀（01_cleaned 等，体现管线顺序）✅
3. **dpo/v0.5 的 train 命名**：保留子目录（dpo/v0.5/format/、v1/、v2/）✅
