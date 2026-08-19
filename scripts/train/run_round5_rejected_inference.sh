#!/bin/bash
# Round 5 重做：SFT V4 推理生成拒答 rejected（460）+ 审慎度 rejected（448）
cd "$(dirname "$0")/../.."
# source <你的 miniconda>/etc/profile.d/conda.sh
# conda activate legalgpt
M=saves/qwen2.5-7b-legal-sft-full-merged

CUDA_VISIBLE_DEVICES=0 python scripts/phase5_dpo/generate/generate_rejected.py \
  --model $M --input data/dpo/v0.5/refusal_input_v5.jsonl \
  --output data/dpo/v0.5/refusal_rejected_v5.jsonl

CUDA_VISIBLE_DEVICES=0 python scripts/phase5_dpo/generate/generate_rejected.py \
  --model $M --input data/dpo/v0.5/prudence_input_v5.jsonl \
  --output data/dpo/v0.5/prudence_rejected_v5.jsonl

echo ALL_DONE
