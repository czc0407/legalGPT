#!/usr/bin/env python3
"""根据人工审核结果清洗训练数据。

流程: 生成 → validate → 审核(HTML) → 导出 -> 本脚本 -> render → isolate → finalize

用法:
    # 清洗卡5 拒答审核结果
    python scripts/phase3_data/clean_dataset.py --audit refusal_audit.json --action remove --card card5

    # 清洗验证审核结果（移除标记为remove的）
    python scripts/phase3_data/clean_dataset.py --audit validation_audit_fixed.json --action remove

    # 只清理条文编号（自动，无需审核）
    python scripts/phase3_data/clean_dataset.py --clean-articles
"""
import json, re, os, argparse

RAW_DIR = "data/sft/04_cards"


def clean_article_numbers(raw_dir: str = RAW_DIR):
    """清除所有 raw 数据中的条文编号。"""
    cleaned = 0
    ids = set()
    for fname in os.listdir(raw_dir):
        if not fname.startswith("card") or not fname.endswith(".jsonl") or "progress" in fname:
            continue
        path = os.path.join(raw_dir, fname)
        with open(path) as f:
            data = [json.loads(l) for l in f if l.strip()]
        for d in data:
            old = d["answer"]
            new_a = re.sub(r"第[零一二三四五六七八九十百千\d]+条(?:之[一二三])?", "", old)
            new_a = re.sub(r"第[零一二三四五六七八九十百千\d]+款", "", new_a)
            if new_a != old:
                d["answer"] = new_a
                cleaned += 1
                ids.add(d["id"])
        with open(path, "w") as f:
            for d in data:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"清理条文编号: {cleaned} 条 (涉及 {len(ids)} 个ID)")
    return cleaned


def apply_audit(audit_path: str, action: str = "remove"):
    """根据审核导出的 JSON，移除标记为 remove 的样本。"""
    with open(audit_path) as f:
        audit = json.load(f)

    # Collect IDs by card number
    to_remove = {}
    for r in audit:
        verdict = r.get("verdict", r.get("action", ""))
        if verdict in ("remove", "move"):
            # Extract card number from ID: sft_card1_2_hualv_xxx -> card1, sft_card3_disc_xxx -> card3
            parts = r["id"].split("_")
            card_num = parts[1] if len(parts) > 1 else ""  # e.g. "card1", "card3"
            # Get just the digit: "card1" -> "1"
            digit = card_num.replace("card", "")
            to_remove.setdefault(digit, set()).add(r["id"])

    total_removed = 0
    for digit, ids in to_remove.items():
        # Find matching file: starts with "card{digit}"
        matched = [f for f in os.listdir(RAW_DIR) if f.startswith(f"card{digit}") and f.endswith(".jsonl") and "progress" not in f]
        if not matched:
            print(f"警告: 找不到卡{card_name}的文件")
            continue
        path = os.path.join(RAW_DIR, matched[0])
        with open(path) as f:
            data = [json.loads(l) for l in f if l.strip()]
        before = len(data)
        data = [d for d in data if d["id"] not in ids]
        removed = before - len(data)
        with open(path, "w") as f:
            for d in data:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"卡{digit}: 移除 {removed} 条 ({before} → {len(data)})")
        total_removed += removed

    print(f"总共移除: {total_removed} 条")
    return total_removed


def main():
    parser = argparse.ArgumentParser(description="根据审核结果清洗训练数据")
    parser.add_argument("--audit", help="审核导出的 JSON 文件路径")
    parser.add_argument("--action", choices=["remove"], default="remove", help="对标记为 remove 的样本执行的操作")
    parser.add_argument("--clean-articles", action="store_true", help="自动清除所有条文编号")
    args = parser.parse_args()

    if not args.clean_articles and not args.audit:
        parser.error("至少需要 --audit 或 --clean-articles")
        return

    if args.clean_articles:
        clean_article_numbers()

    if args.audit:
        apply_audit(args.audit, args.action)


if __name__ == "__main__":
    main()
