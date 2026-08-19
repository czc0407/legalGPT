#!/bin/bash
# LegalGPT 项目文件归档脚本
# 规范见: docs/project-conventions/archiving.md
# 用法:
#   bash archive/archive.sh            # 执行归档
#   bash archive/archive.sh --dry-run  # 预览不执行

set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$PROJECT/archive"

if [ "${1:-}" = "--dry-run" ]; then
    echo "=== DRY RUN (no files will be moved) ==="
    DRY=true
else
    DRY=false
fi

move() {
    local src="$1"
    local dst_dir="$2"
    if $DRY; then
        echo "  [DRY] $src → $dst_dir/"
    else
        if [ -e "$src" ]; then
            mv "$src" "$dst_dir/" 2>/dev/null && echo "  ✓ $src" || echo "  ⚠ $src (move failed, may already exist)"
        else
            echo "  - $src (already moved or absent)"
        fi
    fi
}

movedir() {
    local src="$1"
    local dst_dir="$2"
    if $DRY; then
        echo "  [DRY] $src/ → $dst_dir/"
    else
        if [ -d "$src" ]; then
            local name="$(basename "$src")"
            if [ -n "$(ls -A "$src" 2>/dev/null)" ]; then
                mv "$src" "$dst_dir/" 2>/dev/null && echo "  ✓ $src/" || echo "  ⚠ $src/ (move failed)"
            fi
        else
            echo "  - $src/ (already moved or absent)"
        fi
    fi
}

echo "=== LegalGPT Archive ==="
echo "Project: $PROJECT"
echo "Archive: $ARCHIVE"
echo ""

# ═══════════════════════════════════════════════════════
# A. 评测集旧版本
# ═══════════════════════════════════════════════════════
echo "--- A. old-eval-versions ---"
mkdir -p "$ARCHIVE/old-eval-versions/disc-v1-v4"

cat > "$ARCHIVE/old-eval-versions/README.md" << 'EOF'
# 评测集旧版本归档
# 日期: 2026-08-12

## 说明
DISC eval 经过 5 轮迭代，当前使用 v5 (80条: 45 consult + 35 case)。
保留旧版本以追溯评测集演进历史。

## DISC eval 版本演进
| 版本 | 格式 | 条目 | 说明 |
|------|------|:---:|------|
| v1 | JSONL | 340 | 初次构造 (含类型1) |
| v2 | JSON+JSONL | 340 | 双格式调整 |
| v3 | JSON | - | 移除类型1 (非咨询) |
| v4 | JSON | - | 质量筛选 (去除无引用/强判断) |
| v5 | JSON+JSONL | 80 | **当前使用** —— 45 consult + 35 case |

## 其他归档文件
- eval_v1.jsonl: 旧版行为评测集 (340条) → 被 eval_v2_behavior.jsonl (110条) 取代
- pilot5_questions.jsonl: Pilot 评测问题
- disc_eval_merged.json: DISC 评测中间合并
- disc_rewrite_samples.json: DISC 改写采样记录
- human_labels.json: Phase 2 人工标注 (一次性使用)
EOF

move "$PROJECT/eval/datasets/disc_eval_v1.jsonl"     "$ARCHIVE/old-eval-versions/disc-v1-v4"
move "$PROJECT/eval/datasets/disc_eval_v2.json"      "$ARCHIVE/old-eval-versions/disc-v1-v4"
move "$PROJECT/eval/datasets/disc_eval_v2.jsonl"     "$ARCHIVE/old-eval-versions/disc-v1-v4"
move "$PROJECT/eval/datasets/disc_eval_v3.json"      "$ARCHIVE/old-eval-versions/disc-v1-v4"
move "$PROJECT/eval/datasets/disc_eval_v4.json"      "$ARCHIVE/old-eval-versions/disc-v1-v4"
move "$PROJECT/eval/datasets/eval_v1.jsonl"          "$ARCHIVE/old-eval-versions"
move "$PROJECT/eval/datasets/pilot5_questions.jsonl" "$ARCHIVE/old-eval-versions"
move "$PROJECT/eval/datasets/disc_eval_merged.json"  "$ARCHIVE/old-eval-versions"
move "$PROJECT/eval/datasets/disc_rewrite_samples.json" "$ARCHIVE/old-eval-versions"
move "$PROJECT/eval/datasets/human_labels.json"      "$ARCHIVE/old-eval-versions"

# ═══════════════════════════════════════════════════════
# B. 评测输出旧版本
# ═══════════════════════════════════════════════════════
echo "--- B. old-eval-outputs ---"
mkdir -p "$ARCHIVE/old-eval-outputs"

cat > "$ARCHIVE/old-eval-outputs/README.md" << 'EOF'
# 评测输出旧版本归档
# 日期: 2026-08-12

## 说明
Phase 1-2 的测试跑和基线输出。当前评测输出在服务器上 (eval/outputs/sft_full_*, dpo_beta*_*)。

- answers_baseline.jsonl: M0 baseline (Qwen2.5-7B) 在 340 条 v1 评测集上的回答
- pilot_with_answers.jsonl: Pilot 阶段 (5 条) 的回答
- baseline-0.5B-smoke/: 0.5B 模型冒烟测试 (Phase 1 评测框架验证)
- test-{final,integration,rule,run-save}/: CLI 评测框架集成测试 (Phase 1)
EOF

move "$PROJECT/eval/outputs/answers_baseline.jsonl" "$ARCHIVE/old-eval-outputs"
move "$PROJECT/eval/outputs/pilot_with_answers.jsonl" "$ARCHIVE/old-eval-outputs"
movedir "$PROJECT/eval/outputs/baseline-0.5B-smoke" "$ARCHIVE/old-eval-outputs"
movedir "$PROJECT/eval/outputs/test-final" "$ARCHIVE/old-eval-outputs"
movedir "$PROJECT/eval/outputs/test-integration" "$ARCHIVE/old-eval-outputs"
movedir "$PROJECT/eval/outputs/test-rule" "$ARCHIVE/old-eval-outputs"
movedir "$PROJECT/eval/outputs/test-run-save" "$ARCHIVE/old-eval-outputs"

# ═══════════════════════════════════════════════════════
# C. 废弃脚本 + 废弃产物 + 进度 + 临时
# ═══════════════════════════════════════════════════════
echo "--- C. deprecated (scripts + artifacts + progress + temp) ---"
mkdir -p "$ARCHIVE/deprecated/scripts"
mkdir -p "$ARCHIVE/deprecated/artifacts"

cat > "$ARCHIVE/deprecated/README.md" << 'EOF'
# 废弃脚本 + 废弃产物 + 进度文件 + 临时文件归档
# 日期: 2026-08-12

## 归档原则
正常流程的中间产物（raw_processed / labeled / balanced 的数据文件）全部保留，
这里只归档：失败尝试脚本、废弃产物、进度追踪文件、临时文件。
详见 data-pipeline.md。

## scripts/ —— 废弃脚本
- generate_hualv_answers.py: 早期答案生成尝试，被 build_sft_raw.py 取代
- export_taxonomy_excel.py: 一次性分布分析工具
- reorganize_processed.py: 一次性目录整理（历史遗留）

## artifacts/ —— 废弃产物 + 进度 + 临时
- hualv_answers_generated_sample.jsonl: generate_hualv_answers.py 产物
- taxonomy_distribution.xlsx: export_taxonomy_excel.py 产物
- *_progress.json: 断点续传进度（无复用价值）
- temp/*: 临时文件
EOF

move "$PROJECT/scripts/phase1_data/generate_hualv_answers.py" "$ARCHIVE/deprecated/scripts"
move "$PROJECT/scripts/phase1_data/export_taxonomy_excel.py" "$ARCHIVE/deprecated/scripts"
move "$PROJECT/scripts/phase1_data/reorganize_processed.py" "$ARCHIVE/deprecated/scripts"

move "$PROJECT/data/processed/balanced/hualv_answers_generated_sample.jsonl" "$ARCHIVE/deprecated/artifacts"
move "$PROJECT/data/processed/balanced/hualv_failed_reclassify_progress.json" "$ARCHIVE/deprecated/artifacts"
move "$PROJECT/data/processed/balanced/hualv_generation_progress_sample.json" "$ARCHIVE/deprecated/artifacts"
move "$PROJECT/data/processed/balanced/hualv_relabel_progress.json" "$ARCHIVE/deprecated/artifacts"
move "$PROJECT/data/processed/reports/taxonomy_distribution.xlsx" "$ARCHIVE/deprecated/artifacts"
for f in "$PROJECT/data/processed/temp/"*; do
    [ -e "$f" ] && move "$f" "$ARCHIVE/deprecated/artifacts"
done

# ═══════════════════════════════════════════════════════
# D. 一次性审计工具
# ═══════════════════════════════════════════════════════
echo "--- D. audit-tools ---"
mkdir -p "$ARCHIVE/audit-tools"

cat > "$ARCHIVE/audit-tools/README.md" << 'EOF'
# 审计/评审工具归档
# 日期: 2026-08-12

## 说明
Phase 2 评测校准和 Phase 3 数据审计时使用的浏览器工具。
人工审计已完成，不再使用。

## 文件
- smoke_audit.html: 数据冒烟审计页面
- smoke_data.js / smoke_data.json: 冒烟审计数据
- smoke_review.html / smoke_simple.html / smoke_test.html: 数据质量检查页面
- bakeoff_review.html: SFT vs Baseline 盲评对比
- bakeoff_sft_model.py: 盲评后端脚本
EOF

move "$PROJECT/scripts/tools/smoke_audit.html"   "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/smoke_data.js"      "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/smoke_data.json"    "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/smoke_review.html"  "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/smoke_simple.html"  "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/smoke_test.html"    "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/bakeoff_review.html" "$ARCHIVE/audit-tools"
move "$PROJECT/scripts/tools/bakeoff_sft_model.py" "$ARCHIVE/audit-tools"

# ═══════════════════════════════════════════════════════
# E. 根目录旧配置
# ═══════════════════════════════════════════════════════
echo "--- E. root dataset_info.json ---"
cat > "$ARCHIVE/root-dataset-info-readme.md" << 'EOF'
# 根目录 dataset_info.json (旧版)
# 日期: 2026-08-12 归档
# 原因: 被 data/dataset_info.json 取代。
# 旧版使用相对路径 ("sft/v0.1/train.jsonl")，LLaMA-Factory 实际读取 data/ 下的 dataset_info.json。
EOF
move "$PROJECT/dataset_info.json" "$ARCHIVE"

# ═══════════════════════════════════════════════════════
# F. saves/ 本地残余 PNG
# ═══════════════════════════════════════════════════════
echo "--- F. local saves residuals ---"
if [ -d "$PROJECT/saves" ] && [ -n "$(ls -A "$PROJECT/saves" 2>/dev/null)" ]; then
    mkdir -p "$ARCHIVE/local-saves"
    cat > "$ARCHIVE/local-saves/README.md" << 'EOF'
# 本地 saves 残余文件
# 日期: 2026-08-12
# 原因: 服务端训练时，部分产物被 scp 到本地 project-log 后，
#       saves/ 中残留了这些本地拷贝。正式产物在:
#       - project-log/phase-04-sft-training/training_runs/
#       - project-log/phase-05-dpo-training/training_runs/
EOF
    for f in "$PROJECT/saves/"*; do
        [ -e "$f" ] && move "$f" "$ARCHIVE/local-saves"
    done
fi

echo ""
echo "=== Archive complete ==="
if ! $DRY; then
    echo ""
    echo "Archive contents:"
    find "$ARCHIVE" -type f -not -name "archive.sh" | sort | while read f; do
        size=$(ls -lh "$f" | awk '{print $5}')
        echo "  $size  ${f#$ARCHIVE/}"
    done
fi
