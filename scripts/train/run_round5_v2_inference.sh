#!/bin/bash
# V2 评测推理：concept + behavior + disc
cd "$(dirname "$0")/../.."
# source <你的 miniconda>/etc/profile.d/conda.sh
# conda activate legalgpt
M=saves/qwen2.5-7b-legal-dpo-round5-v2-merged

CUDA_VISIBLE_DEVICES=0 python eval/run_baseline_inference.py \
  --model $M --eval-set eval/datasets/disc_concept_v1.jsonl \
  --output eval/outputs/round5_v2_concept.jsonl

CUDA_VISIBLE_DEVICES=0 python eval/run_baseline_inference.py \
  --model $M --eval-set eval/datasets/eval_v2_behavior.jsonl \
  --output eval/outputs/round5_v2_behavior.jsonl

CUDA_VISIBLE_DEVICES=0 python eval/run_baseline_inference.py \
  --model $M --eval-set eval/datasets/disc_eval_v5.jsonl \
  --output eval/outputs/round5_v2_disc.jsonl

echo ALL_DONE
