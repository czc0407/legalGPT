#!/usr/bin/env python3
"""基座模型推理脚本。加载模型 → 逐条生成 → 实时写入 JSONL → 支持断点续传。

用法:
    python eval/run_baseline_inference.py --model Qwen/Qwen2.5-0.5B-Instruct --eval-set eval_v1.jsonl --output answers_baseline.jsonl
"""
import json
import argparse
import sys
import os
import time
from pathlib import Path

# eval/ → project_root/
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
from prompt_template import EVAL_INSTRUCTION


def load_eval_set(path: str) -> list[dict]:
    """加载评测集 JSONL。"""
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    parser = argparse.ArgumentParser(description="基座模型推理")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--eval-set", default="eval/datasets/eval_v1.jsonl")
    parser.add_argument("--output", default="eval/outputs/answers_baseline.jsonl")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    print(f"加载评测集: {args.eval_set}")
    eval_data = load_eval_set(args.eval_set)
    print(f"评测集: {len(eval_data)} 条")

    # 断点续传
    done_ids = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    try:
                        done_ids.add(json.loads(line)["question_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
        print(f"已完成: {len(done_ids)} 条")

    pending = [d for d in eval_data if d["question_id"] not in done_ids]
    print(f"待处理: {len(pending)} 条")

    if not pending:
        print("全部完成！")
        return

    # 延迟导入（避免验证时加载 torch）
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"加载模型: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.float16,
        device_map="cuda",
        trust_remote_code=True,
    )
    model.eval()
    print(f"模型已加载 (device=cuda, dtype=float16)")

    total = len(pending)
    start_time = time.time()
    for i, item in enumerate(pending):
        messages = [
            {"role": "system", "content": EVAL_INSTRUCTION},
            {"role": "user", "content": item["question"]},
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
        answer = tokenizer.decode(generated, skip_special_tokens=True)

        out = {
            "question_id": item["question_id"],
            "question": item["question"],
            "answer": answer,
            "is_out_of_scope": item.get("is_out_of_scope", False),
        }

        # 追加写入
        with open(args.output, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

        if (i + 1) % 10 == 0 or i == total - 1:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  进度: {i+1}/{total} ({(i+1)*100//total}%)  "
                  f"速率: {rate:.1f}条/s  近条均长: {len(answer)}字")

    elapsed = time.time() - start_time
    print(f"推理完成: {args.output} ({elapsed:.0f}s)")
    print(f"总条数: {len(done_ids) + len(pending)}")


if __name__ == "__main__":
    main()
