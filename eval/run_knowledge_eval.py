#!/usr/bin/env python3
"""Layer 1: 法律知识保真度评测（DISC-Law-Eval 客观题）。

在 base 模型上跑客观选择题，建立 accuracy 基线。SFT 后重跑对比，
检测训练是否导致知识退化（accuracy 下降 > 5% → 停训排查）。

用法:
    python eval/run_knowledge_eval.py \
      --model ./models/models/qwen--Qwen2.5-7B-Instruct/snapshots/master \
      --disc-data ../DISC-LawLLM/eval/datasets/objective \
      --output results/M0_knowledge.json
"""
import csv, json, os, re, sys, time, argparse
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

PROMPT = """请回答以下法律选择题。先给出推理过程，最后一行单独输出"答案：X"（X为选项字母）。

题目：{question}
{options}

请作答："""


def load_disc_data(data_dir: str) -> list[dict]:
    """加载 10 个 CSV 并合并。"""
    all_q = []
    for fname in sorted(Path(data_dir).glob("*.csv")):
        source = fname.stem.replace("mcq_sing_", "").replace("mcq_mult_", "").upper()
        multi = "mult" in fname.stem.lower()
        with open(fname) as f:
            for row in csv.DictReader(f):
                opts = {k: row[k] for k in ["A", "B", "C", "D"] if row.get(k)}
                all_q.append({
                    "question": row["input"],
                    "answer": row["output"].strip().upper(),
                    "options": opts,
                    "source": source,
                    "multi": multi,
                })
    print(f"加载: {len(all_q)} 题 (单选 {sum(1 for q in all_q if not q['multi'])}, "
          f"多选 {sum(1 for q in all_q if q['multi'])})")
    return all_q


def extract_answer(text: str, options: list[str]) -> str:
    """从模型输出中提取答案字母。复用 DISC 的正则模式。"""
    pats = [
        r"答案应?该?[为是]([ABCD,，、\s]+)",
        r"答案是([ABCD,，、\s]+)",
        r"答案([ABCD,，、\s]+)",
        r"选择([ABCD,，、\s]+)",
        r"故?选[:：]?([ABCD,，、\s]+)",
        r"([ABCD,，、\s]+)[\)）]?</s>",
        r"^([ABCD,，、\s]+)[。.]",
    ]
    for pat in pats:
        m = re.search(pat, text)
        if m:
            return re.sub(r'[,，、\s]', '', m.group(1))
    # Fallback: find all A/B/C/D mentions
    letters = re.findall(r'\b([ABCD])\b', text.upper())
    if letters:
        return ''.join(dict.fromkeys(letters))  # dedup preserve order
    return text.strip().upper()[:4]


def format_options(opts: dict) -> str:
    return "\n".join(f"{k}. {v}" for k, v in opts.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--disc-data", default="../DISC-LawLLM/eval/datasets/objective")
    parser.add_argument("--output", default="results/M0_knowledge.json")
    parser.add_argument("--max-samples", type=int, help="限制样本数用于快速验证")
    args = parser.parse_args()

    data = load_disc_data(args.disc_data)
    if args.max_samples:
        data = data[:args.max_samples]

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    print(f"加载模型: {args.model} (device={device})")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=dtype, trust_remote_code=True)
    if device == "cuda":
        model = model.cuda()
    model.eval()

    total = len(data)
    correct = 0
    by_source = defaultdict(lambda: {"correct": 0, "total": 0})
    results = []
    start = time.time()

    for i, item in enumerate(data):
        prompt = PROMPT.format(
            question=item["question"],
            options=format_options(item["options"]),
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1536).to(device)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=200, temperature=0.0,
                                     do_sample=False, pad_token_id=tokenizer.eos_token_id)
        gen = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        pred = extract_answer(gen, list(item["options"].keys()))

        is_correct = (pred == item["answer"])
        if is_correct:
            correct += 1

        src = item["source"]
        by_source[src]["total"] += 1
        if is_correct:
            by_source[src]["correct"] += 1

        results.append({"idx": i, "expected": item["answer"], "predicted": pred, "correct": is_correct})

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            print(f"  [{i+1}/{total}] acc={correct/(i+1)*100:.1f}%  rate={(i+1)/elapsed:.1f}条/s")

    elapsed = time.time() - start
    acc = correct / total * 100
    print(f"\n总题数: {total} | 正确: {correct} | 准确率: {acc:.1f}% | 耗时: {elapsed:.0f}s")
    for src in sorted(by_source.keys()):
        s = by_source[src]
        print(f"  {src}: {s['correct']}/{s['total']} ({s['correct']/s['total']*100:.1f}%)")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    summary = {
        "model": args.model, "total": total, "correct": correct,
        "accuracy": acc, "by_source": dict(by_source), "elapsed_s": elapsed,
    }
    with open(args.output, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"结果: {args.output}")


if __name__ == "__main__":
    main()
