#!/usr/bin/env python3
"""迁移本地训练结果：project-log/*/training_runs → experiments/。

统一训练结果目录结构。用 mv 移动（原子、不丢失），迁移前后统计文件数对比。

用法:
    python scripts/train/migrate_runs.py --dry-run   # 预览
    python scripts/train/migrate_runs.py             # 执行
"""
import os, shutil, sys, argparse
from pathlib import Path

PROJECT = Path(__file__).parent.parent.parent

# 源 → 目标 映射（目录级别）
MAPPING = {
    # SFT
    "project-log/phase-04-sft-training/training_runs/v1":   "experiments/sft/v1-half-baseline",
    "project-log/phase-04-sft-training/training_runs/v2":   "experiments/sft/v2-half-card2fix",
    "project-log/phase-04-sft-training/training_runs/v3":   "experiments/sft/v3-half-bare",
    "project-log/phase-04-sft-training/training_runs/full": "experiments/sft/v4-full-bare",
    # DPO Round 1（作废）
    "project-log/phase-05-dpo-training/training_runs/beta01": "experiments/dpo/round1-beta01",
    "project-log/phase-05-dpo-training/training_runs/beta03": "experiments/dpo/round1-beta03",
    "project-log/phase-05-dpo-training/training_runs/beta05": "experiments/dpo/round1-beta05",
    # DPO Round 2
    "project-log/phase-05-dpo-training/training_runs/round2": "experiments/dpo/round2-first",
    "project-log/phase-05-dpo-training/training_runs/round2_ablation/v2": "experiments/dpo/round2-v2",
    "project-log/phase-05-dpo-training/training_runs/round2_ablation/v3": "experiments/dpo/round2-v3",
    "project-log/phase-05-dpo-training/training_runs/round2_ablation/v4": "experiments/dpo/round2-v4",
    "project-log/phase-05-dpo-training/training_runs/round2_ablation/v5": "experiments/dpo/round2-v5",
    "project-log/phase-05-dpo-training/training_runs/round2_ablation/v6": "experiments/dpo/round2-v6",
}


def count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.rglob("*") if _.is_file())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只预览不执行")
    args = parser.parse_args()

    dry = args.dry_run
    if dry:
        print("=== DRY RUN（不执行移动）===\n")

    total_before = 0
    total_after = 0
    moved = 0

    for src_rel, dst_rel in MAPPING.items():
        src = PROJECT / src_rel
        dst = PROJECT / dst_rel
        if not src.exists():
            print(f"  ⊘ 跳过（源不存在）: {src_rel}")
            continue

        n = count_files(src)
        total_before += n

        if dry:
            print(f"  [DRY] mv {src_rel} ({n} 文件) → {dst_rel}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"  ⚠ 目标已存在，跳过: {dst_rel}")
                total_after += count_files(dst)
                continue
            shutil.move(str(src), str(dst))
            print(f"  ✓ mv {src_rel} ({n} 文件) → {dst_rel}")
            moved += 1

        total_after += n

    print(f"\n=== 汇总 ===")
    print(f"  迁移目录数: {moved}/{len(MAPPING)}")
    print(f"  迁移前文件数: {total_before}")
    print(f"  迁移后文件数: {total_after}")
    if not dry and total_before != total_after:
        print(f"  ⚠️ 文件数不一致！迁移前 {total_before} vs 迁移后 {total_after}")
    elif not dry:
        print(f"  ✅ 文件数一致，无丢失")


if __name__ == "__main__":
    main()
