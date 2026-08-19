# 项目文件归档规范

**版本**: v1.0
**日期**: 2026-08-12

---

## 1. 归档原则

### 1.1 什么该归档

| 类别 | 判断标准 | 示例 |
|------|------|------|
| **旧版本数据** | 有更新版本替代，旧版不再被任何流程引用 | DISC eval v1-v4（v5 是当前版本） |
| **失败尝试/废弃工具** | 被新方案替代，或一次性使用完毕 | generate_hualv_answers.py（被 build_sft_raw 取代） |
| **废弃产物** | 失败尝试/废弃工具的输出 | hualv_answers_generated_sample.jsonl |
| **进度追踪文件** | 断点续传的辅助状态，无复用价值 | *_progress.json |
| **临时文件** | 调试/中间检查的临时输出 | temp/* |
| **测试/调试输出** | 框架开发阶段的集成测试输出 | test-final/, test-integration/ |
| **旧配置** | 被新版本配置替代，旧格式不再兼容当前流程 | 根目录 dataset_info.json |

### 1.2 什么不该归档

| 类别 | 判断标准 | 示例 |
|------|------|------|
| **源头数据** | 所有下游产物的来源 | data/raw_data/* |
| **正常流程产物** | 流程的中间产物和最终产物（即使后续有更新版本，只要属正常流程都保留） | raw_processed/*、labeled/*、balanced/* |
| **流程脚本** | 进入当前或未来可复现的管线 | scripts/phase1_data/*, scripts/phase3_data/* |
| **当前数据** | 被当前流程引用 | eval/datasets/disc_eval_v5.jsonl, data/raw/v0.1/* |
| **设计/计划/日志文档** | 项目记录的一部分 | docs/superpowers/*, project-log/* |
| **活跃配置** | 当前训练/评测使用的配置 | configs/legal_dpo_beta*.yaml |
| **框架代码** | 评测框架核心代码 | eval/cli.py, eval/judge_*.py |

### 1.3 边界判断：保留还是归档？

问自己三个问题：
1. 是源头数据吗？→ 是 → **保留**
2. 是正常流程的产物吗？（中间产物 + 最终产物，即使有过期版本）→ 是 → **保留**
3. 是失败尝试/废弃工具/临时文件吗？→ 是 → **归档**

---

## 2. 归档目录结构

```
archive/
├── README.md                    # 归档总索引
├── old-eval-versions/           # 评测集旧版本
│   ├── README.md                # 版本演进说明
│   └── disc-v1-v4/              # 可分子目录
├── old-eval-outputs/            # 评测输出旧版本
│   └── README.md
├── deprecated/                  # 废弃脚本 + 废弃产物 + 进度 + 临时
│   ├── README.md
│   ├── scripts/                 # 废弃脚本
│   └── artifacts/               # 废弃产物/进度/临时文件
├── audit-tools/                 # 一次性审计/评审工具
│   └── README.md
└── archive.sh                   # 归档执行脚本（可复现）
```

### 2.1 命名规则

- 目录名使用 kebab-case
- 不要使用日期作为目录名（日期在 README 中记录）
- 旧版本数据尽量保留原始文件名，通过子目录组织版本关系

---

## 3. README 格式要求

每个归档子目录 **必须** 包含 `README.md`，至少包含：

```markdown
# [归档类别名称]
# 日期: YYYY-MM-DD
# 说明: [一句话概括这类文件是什么、为什么归档]

## [子目录名] —— [一句话说明]
- 文件名: 说明内容、用途、为什么不再需要
- ...

## 版本演进（如适用）
| 版本 | 说明 |
|------|------|
| v1 | ... |
| vN | **当前使用** |
```

---

## 4. 归档脚本规范

每次归档操作通过 `archive/archive.sh` 执行。脚本要求：

- **幂等性**：多次执行不报错（用 `2>/dev/null` 容忍文件已移动）
- **可预览**：支持 `--dry-run` 只打印操作不执行
- **原子性**：每个类别独立，一个失败不影响其他
- **README 先写**：先创建 README.md，再移动文件

### 4.1 脚本模板

```bash
#!/bin/bash
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$PROJECT/archive"

if [ "${1:-}" = "--dry-run" ]; then
    echo "=== DRY RUN ==="
    DRY=true
else
    DRY=false
fi

move() {
    # move <src> <dst_dir>
    if $DRY; then
        echo "  [DRY] mv $1 → $2/"
    else
        mv "$1" "$2/" 2>/dev/null || true
    fi
}

# ... 各类别归档逻辑
```

---

## 5. 归档触发条件

以下时机应该考虑归档：

| 触发条件 | 归档内容 |
|------|------|
| 评测集发布新版本 | 旧版本评测集 |
| 脚本被新方案替代 | 旧脚本 + 其产物 |
| 训练实验废弃（如 DPO Round 1） | 旧的偏好对数据、旧的训练配置 |
| 工具被新工具替代 | 旧工具脚本 |
| 一次性工具用完 | 工具 + 产物 |

---

## 6. 当前待归档清单 (2026-08-12)

按 §1 标准审查后的待归档文件：

### A. 评测集旧版本 → `archive/old-eval-versions/`
| 文件 | 归档原因 |
|------|------|
| `eval/datasets/disc_eval_v{1,2,2.jsonl,3,4}.json[l]` | v5 是当前版本 |
| `eval/datasets/eval_v1.jsonl` | 被 eval_v2_behavior.jsonl 取代 |
| `eval/datasets/pilot5_questions.jsonl` | Pilot 阶段，不再使用 |
| `eval/datasets/disc_eval_merged.json` | 中间合并文件 |
| `eval/datasets/disc_rewrite_samples.json` | DISC 改写采样记录 |
| `eval/datasets/human_labels.json` | 一次性人工标注数据 |

### B. 评测输出旧版本 → `archive/old-eval-outputs/`
| 文件 | 归档原因 |
|------|------|
| `eval/outputs/answers_baseline.jsonl` | Phase 1 M0 baseline，评测集已换代 |
| `eval/outputs/pilot_with_answers.jsonl` | Pilot 阶段 |
| `eval/outputs/baseline-0.5B-smoke/` | 0.5B 冒烟测试 |
| `eval/outputs/test-{final,integration,rule,run-save}/` | CLI 框架集成测试 |

### C. 废弃脚本 + 废弃产物 + 进度 + 临时 → `archive/deprecated/`
| 文件 | 归档原因 |
|------|------|
| `scripts/phase1_data/generate_hualv_answers.py` | 被 build_sft_raw.py 取代 |
| `scripts/phase1_data/export_taxonomy_excel.py` | 一次性分析工具 |
| `scripts/phase1_data/reorganize_processed.py` | 一次性目录整理（历史遗留） |
| `data/processed/balanced/hualv_answers_generated_sample.jsonl` | 废弃脚本产物 |
| `data/processed/balanced/*_progress.json` | 进度追踪文件（无复用价值） |
| `data/processed/reports/taxonomy_distribution.xlsx` | 废弃脚本产物 |
| `data/processed/temp/*` | 临时文件 |

### D. 一次性审计工具 → `archive/audit-tools/`
| 文件 | 归档原因 |
|------|------|
| `scripts/tools/smoke_*` | Phase 3 数据冒烟审计 |
| `scripts/tools/bakeoff_*` | Phase 2 盲评对比 |

### E. 根目录旧配置
| 文件 | 归档原因 |
|------|------|
| `dataset_info.json` | 被 `data/dataset_info.json` 取代 |

### F. 本地残留
| 文件 | 归档原因 |
|------|------|
| `saves/*.png` | 服务器上训练时的本地残留拷贝（正式产物在 project-log） |
