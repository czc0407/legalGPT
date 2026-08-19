#!/bin/bash
# 阶段三 · 数据构造管线编排
# 用法: bash scripts/phase3_data/build_dataset.sh [smoke|full]

set -e
MODE=${1:-smoke}

echo "=========================================="
echo " Phase 3 Dataset Pipeline — $MODE"
echo "=========================================="

SCRIPTS="scripts/phase3_data"

if [ "$MODE" = "smoke" ]; then
    FLAG="--smoke"
elif [ "$MODE" = "full" ]; then
    FLAG="--full"
else
    echo "Usage: $0 [smoke|full]"
    exit 1
fi

echo ""
echo "[1/7] 生成 raw 数据..."
python $SCRIPTS/build_sft_raw.py $FLAG

echo ""
echo "[2/7] 生成拒答样本..."
python $SCRIPTS/build_refusals.py $FLAG

echo ""
echo "[3/7] 质量校验..."
python $SCRIPTS/validate_raw.py

echo ""
echo "[4/7] SFT 渲染..."
python $SCRIPTS/render_sft.py

echo ""
echo "[5/7] DPO 扰动..."
python $SCRIPTS/perturb_dpo.py

echo ""
echo "[6/7] 训评隔离..."
python $SCRIPTS/check_isolation.py

echo ""
echo "[7/7] 切分 + 版本..."
python $SCRIPTS/finalize_dataset.py

echo ""
echo "=========================================="
echo " Pipeline Complete!"
echo "=========================================="
