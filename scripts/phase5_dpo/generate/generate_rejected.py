#!/usr/bin/env python3
"""用 SFT V4 模型对 DPO 候选问题生成 rejected（模型真实行为）。

用法:
    python scripts/phase5_dpo/generate_rejected.py \
        --model saves/qwen2.5-7b-legal-sft-full-merged \
        --input data/dpo/v0.2/dpo_candidate_questions.jsonl \
        --output data/dpo/v0.2/dpo_rejected.jsonl
"""
import json, os, sys, time, argparse
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "eval"))
from prompt_template import EVAL_INSTRUCTION


def main():
    parser = argparse.ArgumentParser(description="SFT 模型生成 rejected")
    parser.add_argument("--model", default="saves/qwen2.5-7b-legal-sft-full-merged")
    parser.add_argument("--input", default="data/dpo/v0.2/dpo_candidate_questions.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.2/dpo_rejected.jsonl")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    # 加载候选问题
    with open(args.input) as f:
        candidates = [json.loads(l) for l in f if l.strip()]
    print(f"候选问题: {len(candidates)}")

    # 断点续传（按 question 去重）
    done_questions = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for l in f:
                if l.strip():
                    done_questions.add(json.loads(l)["question"])
    pending = [c for c in candidates if c["question"] not in done_questions]
    print(f"已完成: {len(done_questions)}，待处理: {len(pending)}")

    if not pending:
        print("全部完成")
        return

    # 加载模型
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    print(f"加载模型: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float16, device_map="cuda", trust_remote_code=True
    )
    model.eval()
    print("模型已加载")

    total = len(pending)
    for i, c in enumerate(pending):
        messages = [
            {"role": "system", "content": EVAL_INSTRUCTION},
            {"role": "user", "content": c["question"]},
        ]
        encoded = tokenizer.apply_chat_template(
            messages, return_tensors="pt", truncation=True, max_length=1536, add_generation_prompt=True
        )
        input_ids = encoded["input_ids"] if hasattr(encoded, "keys") else encoded
        attention_mask = encoded.get("attention_mask") if hasattr(encoded, "keys") else None
        if torch.cuda.is_available():
            input_ids = input_ids.cuda()
            if attention_mask is not None:
                attention_mask = attention_mask.cuda()

        with torch.no_grad():
            outputs = model.generate(
                input_ids,
                attention_mask=attention_mask,
                max_new_tokens=args.max_new_tokens,
                temperature=0.0,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = outputs[0][input_ids.shape[1]:]
        rejected = tokenizer.decode(generated, skip_special_tokens=True)

        out = dict(c)
        out["rejected"] = rejected

        with open(args.output, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

        if (i + 1) % 20 == 0 or i == total - 1:
            print(f"  进度: {i+1}/{total} | 近条 rejected 长度: {len(rejected)}")

    print(f"\n完成: {args.output}")


if __name__ == "__main__":
    main()
