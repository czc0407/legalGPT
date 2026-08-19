#!/usr/bin/env python3
"""阶段三 · SFT 渲染器。raw → Alpaca 格式，纯规则渲染。

用法:
    python scripts/phase3_data/render_sft.py [--input data/sft/04_cards/] [--output data/sft/05_train/]
"""
import json, os, sys, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, PROJECT_DIR)

# 训练与评测统一使用 bare system prompt。
# 模型应从数据本身学会回答方式，而非依赖 instruction 指令。
# 参考: DISC-LawLLM eval prompt, Train-Before-Test (2025)
INSTRUCTION = "你是一名中国法律专家。"

# 卡 6（知识问答）使用独立的轻量 instruction，与咨询卡区分。
# 模型应通过 instruction 差异学会区分"简洁回答"和"完整推理"。
KNOWLEDGE_INSTRUCTION = "请简洁准确地回答以下法律问题，引用具体法律依据。"

def render_all(raw_dir: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    all_sft = []
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.startswith("card") or not fname.endswith(".jsonl"):
            continue
        if "progress" in fname:
            continue

        path = os.path.join(raw_dir, fname)
        print(f"  {fname}...", end=" ")
        count = 0
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not raw.get("answer"):
                    continue
                # 卡 6 使用轻量知识问答 instruction
                inst = KNOWLEDGE_INSTRUCTION if raw.get("card") == 6 else INSTRUCTION
                sft = {
                    "instruction": inst,
                    "input": raw["question"],
                    "output": raw["answer"],
                }
                all_sft.append(sft)
                count += 1
        print(f"{count} 条")

    output_file = os.path.join(output_dir, "train.jsonl")
    with open(output_file, "w") as f:
        for s in all_sft:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"\n  总计: {len(all_sft)} 条 → {output_file}")

    # Level 2 校验
    errors = 0
    for s in all_sft:
        if s["instruction"] not in (INSTRUCTION, KNOWLEDGE_INSTRUCTION):
            errors += 1
        if not s["output"]:
            errors += 1
    print(f"  Level 2 校验: {'✅ 通过' if errors == 0 else f'❌ {errors} 条有问题'}")

def main():
    parser = argparse.ArgumentParser(description="SFT 渲染器")
    parser.add_argument("--input", default="data/sft/04_cards/")
    parser.add_argument("--output", default="data/sft/05_train/")
    args = parser.parse_args()
    render_all(args.input, args.output)

if __name__ == "__main__":
    main()
