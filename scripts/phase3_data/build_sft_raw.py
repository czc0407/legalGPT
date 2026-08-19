#!/usr/bin/env python3
"""阶段三 · 原始数据生成器。按 Prompt A/B/C 调 deepseek-chat，产出卡 1-4 的 raw 样本。

用法:
    python scripts/build_sft_raw.py --smoke          # 小样冒烟（每 prompt 10 条）
    python scripts/build_sft_raw.py --full            # 全量生成
    python scripts/build_sft_raw.py --card 1 --full   # 只生成指定卡
"""
import json, os, sys, time, re, random, argparse
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, MAX_RETRIES, SLEEP_BETWEEN
from sft_prompts import CARD_CONFIGS

MODEL_NAME = "deepseek-chat"
GEN_MAX_TOKENS = 500   # 宽于篇幅上限，不靠截断控篇幅
TEMPERATURE = 0.3

RAW_DIR = "data/sft/04_cards"
HUALV_INPUT = "data/sft/03_balanced/hualv_questions_to_label.jsonl"
RETAINED_INPUT = "data/sft/03_balanced/consultation_retained.jsonl"

# ═══════════════════════════════════════════════════════════════
# 滚动质量检查
# ═══════════════════════════════════════════════════════════════

WARNING_THRESHOLDS = {
    "条文编号": 0.10,
    "框架标签词": 0.15,
    "绝对化措辞": 0.20,
}

def rolling_quality_check(samples: list[dict], label: str) -> list[str]:
    """对已生成样本跑 Level 1 正则检查，打印统计，返回触发警告的项。"""
    n = len(samples)
    if n == 0:
        return []
    article_hits = 0
    label_hits = 0
    absolutist_hits = 0
    for s in samples:
        answer = s.get("answer", "")
        if re.search(r'第[零一二三四五六七八九十百千\d]+条', answer):
            article_hits += 1
        if len(re.findall(r'(?:^|\n)(?:首先|其次|再次|最后)', answer)) >= 2:
            label_hits += 1
        if re.search(r'[一肯必绝]定[能会要]?|毫无[疑异]问|必然', answer):
            absolutist_hits += 1

    rates = {"条文编号": article_hits / n, "框架标签词": label_hits / n, "绝对化措辞": absolutist_hits / n}

    triggered = []
    parts = []
    for name, rate in rates.items():
        threshold = WARNING_THRESHOLDS[name]
        warn = rate > threshold
        flag = " ⚠" if warn else ""
        parts.append(f"{name}={rate:.1%}{flag}")
        if warn:
            triggered.append(f"{name}: {rate:.1%} (阈值 {threshold:.0%})")
    print(f"  [{label} 质量检查 n={n}] " + " | ".join(parts))
    return triggered

# ═══════════════════════════════════════════════════════════════
# 数据加载与 prompt 组装
# ═══════════════════════════════════════════════════════════════

def load_input_data(config: dict, card_num: int, smoke: bool) -> list[dict]:
    """加载输入数据，应用筛选和采样。"""
    if card_num in (1, 2):
        path = HUALV_INPUT
    else:
        path = RETAINED_INPUT

    with open(path) as f:
        data = [json.loads(l) for l in f if l.strip()]

    # 卡 3/4 按 source 筛选
    if card_num == 3:
        data = [d for d in data if d.get("source") == "DISC-Law-SFT"]
    elif card_num == 4:
        data = [d for d in data if d.get("source") == "zixun_gpt4"]

    # 卡 3/4：映射 retained 字段 → raw 字段
    if card_num in (3, 4):
        for d in data:
            if "response" in d and "original_answer" not in d:
                d["original_answer"] = d["response"]
            if "query" in d and "question" not in d:
                d["question"] = d["query"]

    # 冒烟采样
    if smoke:
        random.seed(42)
        if card_num == 1:
            # 卡 1 冒烟：取 question 最长的 6 条（偏信息充足）
            data = sorted(data, key=lambda d: len(d.get("question", "")), reverse=True)[:6]
        elif card_num == 2:
            # 卡 2 冒烟：取 question 最短的 4 条（偏信息不足），独立标注 card=2
            data = sorted(data, key=lambda d: len(d.get("question", "")))[:4]
        else:
            data = random.sample(data, min(10, len(data)))

    # 卡 2 全量：只取信息不足
    if not smoke and card_num == 2:
        data = [d for d in data if len(d.get("question", "")) <= 30]

    return data


def build_user_prompt(config: dict, item: dict) -> str:
    """模板变量替换。"""
    tpl = config["user_template"]
    for var in config["template_vars"]:
        tpl = tpl.replace("{" + var + "}", str(item.get(var, "")))
    return tpl

# ═══════════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════════

def call_api(client: OpenAI, system_prompt: str, user_prompt: str) -> Optional[str]:
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=TEMPERATURE,
                max_tokens=GEN_MAX_TOKENS,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if answer and len(answer) >= 50:
                return answer
            print(f"    回答过短 ({len(answer)} 字)，重试 {attempt + 1}")
        except Exception as e:
            print(f"    API 错误 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(3 * (attempt + 1))
    return None

# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def generate_card(config: dict, card_num: int, smoke: bool):
    os.makedirs(RAW_DIR, exist_ok=True)

    card_name = config["name"]
    output_file = os.path.join(RAW_DIR, f"{card_name}.jsonl")
    progress_file = os.path.join(RAW_DIR, f"{card_name}_progress.json")

    print(f"\n{'='*60}")
    print(f"  卡 {card_num}: {card_name} ({config['source']})")
    print(f"{'='*60}")

    all_items = load_input_data(config, card_num, smoke)
    if not all_items:
        print("  无数据")
        return
    print(f"  输入: {len(all_items)} 条")

    # 恢复进度
    done_ids = set()
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            done_ids = set(json.load(f).get("done_ids", []))
        print(f"  恢复进度: 已完成 {len(done_ids)} 条")

    # 加载已有输出
    generated = []
    if os.path.exists(output_file):
        with open(output_file) as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    generated.append(item)
                    uid = item.get("hualv_id") or item.get("retained_id", "")
                    if uid:
                        done_ids.add(uid)
        print(f"  已有输出: {len(generated)} 条")

    pending = []
    for d in all_items:
        uid = d.get("hualv_id") or d.get("id", "")
        if uid not in done_ids:
            pending.append(d)
    print(f"  待处理: {len(pending)} 条")
    if not pending:
        print("  全部完成！")
        return

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    total = len(pending)
    start_time = time.time()

    for i, item in enumerate(pending):
        user_prompt = build_user_prompt(config, item)
        answer = call_api(client, config["system_prompt"], user_prompt)

        if not answer:
            print(f"  生成失败: {str(item.get('question', ''))[:50]}...")
            answer = ""

        out = {
            "id": f"sft_{card_name}_{len(generated) + 1:06d}",
            "card": config["output_fields"]["card"],
            "source": config["output_fields"]["source"],
            "generator_model": MODEL_NAME,
            "category": item.get("category", item.get("label", "")),
            "dpo_targets": [],
            "question": item.get("question", ""),
            "answer": answer,
        }
        for ef in config.get("extra_fields", []):
            out[ef] = item.get(ef, "")

        uid = item.get("hualv_id") or item.get("id", "")
        out["hualv_id" if "hualv_id" in item else "retained_id"] = uid

        generated.append(out)
        done_ids.add(uid)

        # 每 10 条保存
        if (i + 1) % 10 == 0 or i == total - 1:
            with open(output_file, "w") as f:
                for g in generated:
                    f.write(json.dumps(g, ensure_ascii=False) + "\n")
            with open(progress_file, "w") as f:
                json.dump({"done_ids": list(done_ids), "total": len(all_items)}, f)

        # 进度 + 滚动质量检查
        if (i + 1) % 10 == 0 or i == total - 1:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            recent_lens = [len(g["answer"]) for g in generated[-20:]]
            avg_len = sum(recent_lens) / len(recent_lens)
            done = len(done_ids)
            print(f"  进度: {done}/{len(all_items)} ({done * 100 // len(all_items)}%) "
                  f"| 速率: {rate:.1f}条/s | 近20条均长: {avg_len:.0f}字")

            # 全量模式每 50 条滚动检查
            if not smoke and len(generated) >= 50 and len(generated) % 50 == 0:
                triggered = rolling_quality_check(generated[-50:], f"卡{card_num}")
                for t in triggered:
                    print(f"    ⚠ {t}")

        time.sleep(SLEEP_BETWEEN)

    # 最终统计
    lens = [len(g["answer"]) for g in generated if g["answer"]]
    failures = sum(1 for g in generated if not g["answer"])
    if lens:
        print(f"  完成: {len(generated)} 条 | 均长: {sum(lens)//len(lens)} 字 "
              f"(min={min(lens)}, max={max(lens)}) | 失败: {failures} 条")

    if not smoke and generated:
        triggered = rolling_quality_check(generated, f"卡{card_num} 最终")
        if triggered:
            print(f"  ⚠ 警告项: {'; '.join(triggered)}")

# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="阶段三 raw 数据生成")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--smoke", action="store_true", help="小样冒烟（每 prompt 10 条）")
    g.add_argument("--full", action="store_true", help="全量生成")
    parser.add_argument("--card", type=int, nargs="+", help="只生成指定卡 (1-4)")
    args = parser.parse_args()

    smoke = args.smoke
    target = set(args.card) if args.card else set()

    if target:
        cards = sorted(target)
    else:
        # 默认顺序：卡 3(DISC, 数据小) → 卡 4(zixun, 数据小) → 卡 1+2(华律网, 数据大)
        cards = [3, 4, 1]

    print(f"阶段三 · raw 数据生成 | 模式: {'冒烟(10条/卡)' if smoke else '全量'} | 模型: {MODEL_NAME}")
    print(f"  卡: {cards} | 输出: {RAW_DIR}/")

    # 卡 1 和 2 共享数据和 prompt——卡 2 在全量时只做筛选，冒烟时由卡 1 覆盖
    for c in cards:
        config = CARD_CONFIGS[c]
        generate_card(config, c, smoke)

    print(f"\n{'='*60}")
    print(f"  全部完成 → {RAW_DIR}/")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
