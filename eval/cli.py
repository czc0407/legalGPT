#!/usr/bin/env python3
"""评测 CLI 入口。统一调度规则检测 + 四个 Panel Judge + 分数卡。

用法:
    # 完整评测
    python eval/cli.py --run-name baseline
    python eval/cli.py --run-name sft

    # 只跑某个 Panel
    python eval/cli.py --run-name sft --panel checklist
    python eval/cli.py --run-name sft --panel quality
    python eval/cli.py --run-name sft --panel prudence

约定: eval/outputs/{run-name}_disc.jsonl, {run-name}_concept.jsonl, {run-name}_behavior.jsonl 已存在
"""
import json, os, sys, argparse, subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_DIR / "eval" / "outputs"
SCRIPTS_DIR = PROJECT_DIR / "scripts" / "phase2_eval"

sys.path.insert(0, str(PROJECT_DIR))


def run_step(cmd: list[str], desc: str):
    print(f"\n{'='*50}")
    print(f"  {desc}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    if result.returncode != 0:
        print(f"❌ {desc} 失败")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="LegalGPT 评测框架 (v2)")
    parser.add_argument("--run-name", required=True, help="运行名称，eval/outputs/{run-name}_*.jsonl")
    parser.add_argument("--panel", choices=["all", "rules", "checklist", "quality", "prudence", "refusal"],
                        default="all", help="只跑指定 Panel (默认all)")
    parser.add_argument("--layer1", help="Layer 1 知识评测 JSON 路径")
    args = parser.parse_args()

    run = args.run_name
    all_ok = True

    # ── Panel A: Rules ──
    if args.panel in ("all", "rules"):
        for label, input_file in [("disc", f"eval/outputs/{run}_disc.jsonl"), ("concept", f"eval/outputs/{run}_concept.jsonl"), ("behavior", f"eval/outputs/{run}_behavior.jsonl")]:
            path = OUTPUTS_DIR / f"{run}_{label}.jsonl"
            if path.exists():
                rule_out = str(path.parent / f"rule_{label}.json")
                code = (
                    "from eval.rule_checks import run_all_rules; import json; "
                    "answers = [json.loads(l) for l in open('" + str(path) + "') if l.strip()]; "
                    "r = run_all_rules(answers); "
                    "json.dump(r, open('" + rule_out + "','w'), ensure_ascii=False, indent=2); "
                    "print('" + label + ": article={:.1f}% abs={:.1f}% meta={:.1f}% followup={:.1f}% refuse_acc={:.1f}%'.format("
                    "r['article_citation_rate']*100, r['absolutist_rate']*100, r['metacommentary_rate']*100, "
                    "r['followup_rate']*100, r['refusal']['accuracy']*100))"
                )
                all_ok &= run_step([sys.executable, "-c", code], "Panel A 规则检测 (" + label + ")")

    # ── Panel B: Checklist ──
    if args.panel in ("all", "checklist"):
        for label, eval_set in [("disc", "eval/datasets/disc_eval_v5.json"), ("concept", "eval/datasets/disc_concept_v1.jsonl")]:
            answers_file = OUTPUTS_DIR / f"{run}_{label}.jsonl"
            if answers_file.exists():
                all_ok &= run_step([
                    sys.executable, "eval/judge_checklist.py",
                    "--answers", str(answers_file),
                    "--eval-set", str(PROJECT_DIR / eval_set),
                    "--output", str(OUTPUTS_DIR / f"{run}_checklist_{label}.jsonl"),
                ], f"Panel B Checklist ({label})")

    # ── Panel C: Quality ──
    if args.panel in ("all", "quality"):
        disc_file = OUTPUTS_DIR / f"{run}_disc.jsonl"
        if disc_file.exists():
            all_ok &= run_step([
                sys.executable, "eval/judge_quality.py",
                "--answers", str(disc_file),
                "--output", str(OUTPUTS_DIR / f"{run}_quality.jsonl"),
            ], "Panel C 质量维度")

    # ── Panel D: Prudence + Refusal ──
    if args.panel in ("all", "prudence", "refusal"):
        behavior_file = OUTPUTS_DIR / f"{run}_behavior.jsonl"
        if behavior_file.exists():
            if args.panel in ("all", "prudence"):
                all_ok &= run_step([
                    sys.executable, "eval/judge_prudence.py",
                    "--answers", str(behavior_file),
                    "--eval-set", str(PROJECT_DIR / "eval/datasets/eval_v2_behavior.jsonl"),
                    "--output", str(OUTPUTS_DIR / f"{run}_prudence.jsonl"),
                ], "Panel D-1 信息审慎度")
            if args.panel in ("all", "refusal"):
                all_ok &= run_step([
                    sys.executable, "eval/judge_refusal.py",
                    "--answers", str(behavior_file),
                    "--eval-set", str(PROJECT_DIR / "eval/datasets/eval_v2_behavior.jsonl"),
                    "--output", str(OUTPUTS_DIR / f"{run}_refusal.jsonl"),
                ], "Panel D-2 拒答质量")

    # ── Scorecard ──
    if args.panel == "all":
        cmd = [sys.executable, "eval/scorecard.py", "--run", run]
        if args.layer1:
            cmd += ["--layer1", args.layer1]
        cmd += ["--output", f"results/{run}_scorecard.json"]
        all_ok &= run_step(cmd, "生成分数卡")

    if all_ok:
        print(f"\n✅ 评测完成: {run}")
    else:
        print(f"\n⚠️ 部分步骤失败，请检查上方输出")


if __name__ == "__main__":
    main()
