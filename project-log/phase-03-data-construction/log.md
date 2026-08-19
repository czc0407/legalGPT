# 阶段 03 · 训练数据集制作

> 对应 `LegalGPT-postTraing-Spec.md` 3.3。
> 来源：`docs/handoff/2026-07-29_phase3_pipeline_built.md`、`2026-07-30_phase3_progress.md`、`2026-08-04_phase3_cleanup.md`、会话记录。

---

## 1. 该阶段实现目标

> 设计并实现完整的数据构造管线，产出 ~8,000 条 SFT 训练数据 + DPO 扰动方案。

### 1.1 交付线（DoD）与达成情况

| # | 交付线 | 状态 |
|---|---|---|
| 1 | 5 张规格卡 + 4 个生成 Prompt 设计 | ✅ |
| 2 | 全量 raw 数据生成（~7,600 条） | ✅ 实际 8,048 |
| 3 | 三级质量校验 + PPL 异常检测设计 | ✅ |
| 4 | 训评隔离指纹硬去重 | ✅ 零重叠 |
| 5 | 9:1 分层切分，冻结 v0.1 | ✅ 训练 7,207/验证 800 |
| 6 | 数据清洗闭环管线 | ✅ `clean_pipeline.sh` |
| 7 | 卡 6 知识问答补充 | ✅ 500 条 |

### 1.2 不在本阶段范围的

| 不在阶段三 | 归属 |
|---|---|
| DPO 扰动数据实际生成 | 等 SFT 完成后，根据结果调整策略再跑 |
| SFT 训练 | 阶段四 |
| 文档重构 | 后续 |

---

## 2. 实现方法

### 2.1 数据设计（7/29-7/30）

**六张规格卡**（卡 6 为 8/3 补充）：

| 卡 | 名称 | 数量 | 生成方式 |
|:--:|------|-----:|------|
| 1 | 华律网·信息充分 | ~3,700 | 从零生成（Prompt A） |
| 2 | 华律网·信息不足 | ~700 | 从零生成（Prompt A） |
| 3 | DISC 重写（短→长） | 2,696 | 保留结论+补推理链（Prompt B） |
| 4 | zixun 重写（公式→自然） | 348 | 保留结论+去壳（Prompt C） |
| 5 | 拒答 | 100→79 | LLM 参数化生成（Prompt D） |
| 6 | 知识问答 | 500 | DISC 直接抽取（Prompt E） |

**四个 Prompt**：A（从零生成）、B（DISC 重写）、C（zixun 重写）、D（拒答）、E（知识问答，8/3 新增）。

**关键决策**：
- 生成模型选 deepseek-chat：法律推理深度 > 格式合规（格式问题通过质量门修复）
- Canonical 格式：理解处境 → 定性 → 说理 → 建议（4 段式，自然段落）
- 标签词规则：框架用途（"首先/其次/最后"）禁止，功能性列举（"第一/第二"）允许
- 训练数据用 full prompt 采集（详细指令），评测用 bare prompt

### 2.2 管线构建（7/29 完成）

| 模块 | 脚本 | 功能 |
|------|------|------|
| raw 生成 | `build_sft_raw.py` | 卡 1-4 数据生成 |
| 拒答生成 | `build_refusals.py` | 卡 5 参数化拒答 |
| 知识问答 | `build_knowledge_qa.py` | 卡 6 抽取筛选 |
| 质量校验 | `validate_raw.py` | 7 项硬检查 |
| SFT 渲染 | `render_sft.py` | raw → Alpaca |
| DPO 扰动 | `perturb_dpo.py` | P2-P6 扰动 |
| 隔离检查 | `check_isolation.py` | MD5 指纹去重 |
| 数据集冻结 | `finalize_dataset.py` | 9:1 split + 版本卡 |
| 管线编排 | `build_dataset.sh` → `clean_pipeline.sh` | 一键执行 |

### 2.3 冒烟审计（7/30）

40 条逐条审计发现并修复三个问题：
- 卡 1+2 模板化：few-shot 被学成模板，换掉示例 + 正面提示修复
- 卡 5 重复 user_input：20 场景 × 5 次 → 100 不同输入各 1 次
- 绝对化检测假阳性：正收纳窄 + 否定前缀排除

### 2.4 全量生成（7/30-8/3）

| 卡 | 条数 | 状态 | 均值长度 |
|:--:|-----|:--:|:--:|
| 1+2 | 4,404 | ✅ | 521字 |
| 3 | 2,696 | ✅ | 479字 |
| 4 | 348 | ✅ | 444字 |
| 5 | 100→79 | ✅ | — |
| 6 | 500 | ✅ | 473字 |

训练数据长度分布：卡 1+2 偏长（61% >500），卡 4 最克制（14% >500）。决策：评测不加长度硬指标。

### 2.5 数据清洗闭环（8/4）

**问题发现**：
- `validate_raw.py` 的 `check_card34_consistency` 未做法律名归一化（`婚姻法` vs `中华人民共和国婚姻法` 误报为丢失）
- 卡 6 应允许条文编号（知识问答需具体条款）
- 卡 5 生成质量存疑：21 条不应拒答（如"担保责任""合伙纠纷"误标记为拒答）

**解决方案**：
- 修复 `check_card34_consistency`：加 `_normalize_law_name`
- 卡 6 跳过 `check_article`
- 建立标准化清洗管线（`clean_pipeline.sh`）：

```
validate → auto-clean → re-validate → 
  人工审核（HTML 页面） → 导出 JSON → 
  apply audit → re-validate → 
  render → isolate → finalize
```

**审核工具**：
- `audit_validation.html`：硬伤审核（含归一化法律名比对，区分"真正丢失"和"去前缀等价"）
- `audit_refusals.html`：卡 5 拒答质量审核

### 2.6 数据集变更历史

| 操作 | 影响 |
|------|------|
| 初始生成 | 8,048 条 |
| 删除 Q/A 错配（卡 3 #001463：被车撞→农田大棚） | -1 |
| 清理条文编号（卡 1 6 条） | 修复 |
| 拒答审核：不应拒答 | -21 |
| 验证审核：丢失法律 + 条文编号 | -17 |
| 评测集重叠移除 | -2 |
| **最终** | **训练 7,207 + 验证 800 = 8,007 条** |

---

## 3. 重点关注和学习

### 3.1 生成模型的选择逻辑

GPT-4o-mini 90% 长度合规但推理浅，deepseek-chat 30% 合规但推理深。选择后者——**推理质量优先于格式合规**。格式问题通过质量门（`validate_raw.py`）和 DPO 偏好对修复。

### 3.2 法律名白名单的构建

放弃手写名单（~50 部），改用 NPC 公报 306 部现行法律 + 常用法规。`build_legal_whitelist.py` 从官方来源构建。后续发现白名单含已废止法律（《婚姻法》《合同法》等 2021 年被《民法典》取代），决定保留（模型训练数据可能 predates 2021），但在验证中做归一化处理。

### 3.3 自动修复的边界

`auto_fix_answer` 只修两种：删框架标签词（"首先/其次/最后"）、删条文编号。不修的内容（长度、法律名、案情编造）只报告不修改。自动修复后需 re-validate 确认未引入新错误。

### 3.4 清洗流程的教训

数据清洗最易出错的是**遗漏步骤**。手工跑 validate → render → finalize 容易跳过中间环节，导致"修了这个忘了那个"。解决方案：把流程代码化进 `clean_pipeline.sh`，人工审核步骤用 `read -p` 暂停，后续步骤自动执行。

### 3.5 卡 5 拒答的边界模糊

Prompt D 的拒答标准偏松——100 条中有 21 条是正常法律咨询（"我和合伙人闹翻了""我给人做担保"），不应拒答。LLM 难以区分"超出能力"和"应该回答但需要更多信息"，这会延续到 DPO P6 的扰动质量。

---

## 4. 决策与产物小结

**关键决策**：

- 五张卡 → 六张卡（新增知识问答）
- 生成用 deepseek-chat（推理优先）
- 质量门只读不写，自动修复边界明确
- 法律名归一化 + 卡 6 条文编号豁免
- 清洗流程管线化 → `clean_pipeline.sh`
- DPO 等 SFT 结果后再生成
- 评测集与训练集指纹硬去重

**主要产物**：

- `data/processed/sft/v0.1/train.jsonl`：SFT 训练集 7,207 条
- `data/processed/sft/v0.1/val.jsonl`：SFT 验证集 800 条
- `scripts/phase3_data/build_sft_raw.py`：raw 数据生成
- `scripts/phase3_data/build_refusals.py`：拒答生成
- `scripts/phase3_data/build_knowledge_qa.py`：知识问答抽取
- `scripts/phase3_data/validate_raw.py`：质量校验（含自动修复）
- `scripts/phase3_data/render_sft.py`：SFT 渲染
- `scripts/phase3_data/perturb_dpo.py`：DPO 扰动
- `scripts/phase3_data/check_isolation.py`：训评隔离
- `scripts/phase3_data/finalize_dataset.py`：冻结切分
- `scripts/phase3_data/clean_dataset.py`：统一清洗入口
- `scripts/phase3_data/clean_pipeline.sh`：清洗闭环编排
- `scripts/phase3_data/audit_validation.html`：硬伤审核页
- `scripts/phase3_data/audit_refusals.html`：拒答审核页
- `scripts/config/sft_prompts.py`：五个生成 Prompt
- `scripts/config/dpo_assets.py`：DPO 扰动资产
- `scripts/config/legal_name_whitelist.json`：法律名白名单
- `docs/superpowers/specs/phase3-dataset-design.md`：完整设计文档
- `docs/handoff/2026-07-29_phase3_pipeline_built.md`、`2026-07-30_phase3_progress.md`、`2026-08-04_phase3_cleanup.md`
