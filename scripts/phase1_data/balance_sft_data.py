#!/usr/bin/env python3
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
"""
按华律网真实分布调整 SFT 数据分布。

策略：
  1. 11 类分为"核心三类"(80%) + "相邻八类"(20%)
     核心: 婚姻家庭、合同、劳动 — 参考华律网内部占比
     相邻: 其余 8 类 — 参考华律网内部占比
  2. 定总目标 N，算每类目标数
  3. 计算缺口 = 目标 - 现有
     - 缺口 > 0 → 从华律网抽取问题，待生成答案
     - 缺口 < 0 → 从现有中随机降采样（优先保留 DISC，zixun 次之）
  4. 输出采样方案 + 待补充清单
"""

import json
import random
from collections import Counter, defaultdict
from taxonomy_config import LABEL_REMAP

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
TARGET_N = 8000                  # SFT 总目标条数
CORE_RATIO = 0.80                # 核心三类占 80%
RANDOM_SEED = 42

# 11 类
CATEGORIES = [
    "婚姻家庭与继承",
    "债权债务与金融",
    "劳动与工伤",
    "交通事故",
    "合同与商业",
    "人身侵权与消费",
    "房产与土地",
    "刑事法律",
    "公司企业与知产",
    "行政与税务",
    "综合法律服务",
]

CORE_CATS = {"婚姻家庭与继承", "合同与商业", "劳动与工伤"}
ADJACENT_CATS = set(CATEGORIES) - CORE_CATS

# ═══════════════════════════════════════════════════════════════
# 1. 加载华律网分布 → 核心三类内部占比 + 相邻八类内部占比
# ═══════════════════════════════════════════════════════════════
print("=" * 70)
print("  1. 华律网 11 类自然分布")
print("=" * 70)

# 使用清洗后的华律网池子
import os
HUALV_CLEAN = "data/sft/01_cleaned/hualv_question_clean.jsonl"
if not os.path.exists(HUALV_CLEAN):
    print(f"⚠ 清洗后池子不存在: {HUALV_CLEAN}，回退到原始数据")
    HUALV_CLEAN = "data/external/question_2.json"

hualv = Counter()
with open(HUALV_CLEAN) as f:
    for line in f:
        if not line.strip():
            continue
        obj = json.loads(line)
        l1 = obj.get("category_l1", "")
        if l1:
            hualv[l1] += 1
        else:
            title = obj.get("title", "").strip("[]")
            if title in LABEL_REMAP:
                l1, _, _ = LABEL_REMAP[title]
                hualv[l1] += 1
hualv_total = sum(hualv.values())

# 核心三类内部占比（在华律网中）
core_hualv_total = sum(hualv[c] for c in CORE_CATS)
core_weights = {c: hualv[c] / core_hualv_total for c in CORE_CATS}

# 相邻八类内部占比
adj_hualv_total = sum(hualv[c] for c in ADJACENT_CATS)
adj_weights = {c: hualv[c] / adj_hualv_total for c in ADJACENT_CATS}

print(f"  华律网总量: {hualv_total:,}")
print(f"\n  {'类别':<16s} {'华律网':>10s} {'占比':>8s} {'组内%':>8s} {'组'}")
print(f"  {'-'*55}")
for cat in CATEGORIES:
    cnt = hualv[cat]
    pct = cnt / hualv_total * 100
    if cat in CORE_CATS:
        group_pct = cnt / core_hualv_total * 100
        grp = "核心"
    else:
        group_pct = cnt / adj_hualv_total * 100
        grp = "相邻"
    print(f"  {cat:<16s} {cnt:>10,} {pct:>7.2f}% {group_pct:>7.2f}%  {grp}")

# ═══════════════════════════════════════════════════════════════
# 2. 统计现有存量 (DISC + zixun)
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  2. 现有存量统计")
print(f"{'='*70}")

with open("data/sft/02_labeled/consultation_labeled.jsonl") as f:
    labeled = [json.loads(l) for l in f if l.strip()]

existing = Counter()
existing_disc = Counter()
existing_zixun = Counter()
for d in labeled:
    lbl = d["label"]
    existing[lbl] += 1
    if d["source"] == "DISC-Law-SFT":
        existing_disc[lbl] += 1
    else:
        existing_zixun[lbl] += 1

existing_total = sum(existing.values())
print(f"  现有总量: {existing_total:,}  (DISC={sum(existing_disc.values())}, zixun={sum(existing_zixun.values())})\n")
print(f"  {'类别':<16s} {'DISC':>8s} {'zixun':>8s} {'合计':>8s}")
print(f"  {'-'*42}")
for cat in CATEGORIES:
    d = existing_disc.get(cat, 0)
    z = existing_zixun.get(cat, 0)
    print(f"  {cat:<16s} {d:>8,} {z:>8,} {d+z:>8,}")

# ═══════════════════════════════════════════════════════════════
# 3. 计算目标
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  3. 目标分布 (总目标 N={TARGET_N:,}, 核心 {CORE_RATIO*100:.0f}%)")
print(f"{'='*70}")

target = {}
core_budget = int(TARGET_N * CORE_RATIO)
adj_budget = TARGET_N - core_budget

for cat in CATEGORIES:
    if cat in CORE_CATS:
        target[cat] = round(core_budget * core_weights[cat])
    else:
        target[cat] = round(adj_budget * adj_weights[cat])

# 微调使总和等于 TARGET_N
diff = TARGET_N - sum(target.values())
# 按小数部分最大者调整
if diff != 0:
    remainders = {}
    for cat in CATEGORIES:
        if cat in CORE_CATS:
            raw = core_budget * core_weights[cat]
        else:
            raw = adj_budget * adj_weights[cat]
        remainders[cat] = raw - int(raw)
    sorted_cats = sorted(remainders, key=remainders.get, reverse=True)
    for i in range(abs(diff)):
        idx = i if diff > 0 else -(i + 1)
        target[sorted_cats[idx]] += 1 if diff > 0 else -1

print(f"  核心预算: {core_budget:,}  相邻预算: {adj_budget:,}\n")
print(f"  {'类别':<16s} {'目标':>8s} {'现有':>8s} {'缺口':>8s} {'操作'}")
print(f"  {'-'*55}")

gaps = {}
total_keep = 0
total_supplement = 0
oversub_cats = []
undersub_cats = []

for cat in CATEGORIES:
    tgt = target[cat]
    cur = existing.get(cat, 0)
    gap = tgt - cur
    gaps[cat] = gap
    if gap > 0:
        total_keep += cur
        total_supplement += gap
        undersub_cats.append(cat)
        op = f"从华律网补 {gap:,}"
    elif gap < 0:
        total_keep += tgt
        oversub_cats.append(cat)
        op = f"降采样 {abs(gap):,}"
    else:
        total_keep += cur
        op = "刚好"
    print(f"  {cat:<16s} {tgt:>8,} {cur:>8,} {gap:>+8,}  {op}")

print(f"  {'-'*55}")
print(f"  {'合计':<16s} {TARGET_N:>8,} {existing_total:>8,} {TARGET_N - existing_total:>+8,}")
print(f"\n  保留现有: {total_keep:,}  需补充: {total_supplement:,}  需降采样: {existing_total - total_keep:,}")

# ═══════════════════════════════════════════════════════════════
# 4. 生成采样方案
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  4. 采样方案")
print(f"{'='*70}")

random.seed(RANDOM_SEED)

keep_ids = set()
supplement_plan = {}  # cat → {n_supplement, hualv_questions: [...]}

# 4a. 缺口 > 0 的类别：全保留 + 登记需补充量
for cat in undersub_cats:
    cat_items = [d for d in labeled if d["label"] == cat]
    for d in cat_items:
        keep_ids.add(d["id"])
    supplement_plan[cat] = {"need": gaps[cat], "keep": len(cat_items)}

# 4b. 缺口 < 0 的类别：优先保留 DISC high → DISC medium → zixun
for cat in oversub_cats:
    cat_items = [d for d in labeled if d["label"] == cat]
    tgt = target[cat]

    # 排序：DISC-high > DISC-medium > zixun
    def sort_key(d):
        src = 0 if d["source"] == "DISC-Law-SFT" else 1
        qual = 0 if d.get("citation_quality") == "high" else 1
        return (src, qual)

    cat_items.sort(key=sort_key)
    kept = cat_items[:tgt]
    dropped = cat_items[tgt:]

    for d in kept:
        keep_ids.add(d["id"])

    n_dropped_disc = sum(1 for d in dropped if d["source"] == "DISC-Law-SFT")
    n_dropped_zixun = len(dropped) - n_dropped_disc
    supplement_plan[cat] = {
        "keep": len(kept),
        "drop_disc": n_dropped_disc,
        "drop_zixun": n_dropped_zixun,
    }

# ── 输出各分类处理明细 ──
print(f"\n  {'类别':<16s} {'保留':>6s} {'DISC':>6s} {'zixun':>6s} {'丢弃':>6s} {'待补':>6s}")
print(f"  {'-'*55}")
for cat in CATEGORIES:
    plan = supplement_plan[cat]
    need = plan.get("need", 0)
    keep_n = plan["keep"]
    drop_n = plan.get("drop_disc", 0) + plan.get("drop_zixun", 0)
    # count disc/zixun in kept
    kept_items = [d for d in labeled if d["label"] == cat and d["id"] in keep_ids]
    kept_disc = sum(1 for d in kept_items if d["source"] == "DISC-Law-SFT")
    kept_zixun = len(kept_items) - kept_disc
    print(f"  {cat:<16s} {keep_n:>6,} {kept_disc:>6,} {kept_zixun:>6,} {drop_n:>6,} {need:>6,}")

# ── 汇总 ──
print(f"\n  {'─'*55}")
total_keep_final = len(keep_ids)
total_drop = len(labeled) - total_keep_final
print(f"  最终保留: {total_keep_final:,} (DISC + zixun)")
print(f"  丢弃: {total_drop:,}")
print(f"  待从华律网补充: {total_supplement:,}")
print(f"  最终 SFT 规模: {total_keep_final + total_supplement:,}")

# ═══════════════════════════════════════════════════════════════
# 5. 从华律网抽取问题（缺口 > 0 的类别）
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  5. 从华律网抽取待生成问题")
print(f"{'='*70}")

# 使用清洗后的池子：每个对象已有 category_l1 字段
hualv_by_cat = defaultdict(list)
with open(HUALV_CLEAN) as f:
    for line in f:
        if not line.strip():
            continue
        obj = json.loads(line)
        l1 = obj.get("category_l1", "")
        if not l1:
            title = obj.get("title", "").strip("[]")
            if title in LABEL_REMAP:
                l1, _, _ = LABEL_REMAP[title]
        if l1:
            hualv_by_cat[l1].append(obj)

sampled_questions = []
for cat in undersub_cats:
    need = gaps[cat]
    pool = hualv_by_cat.get(cat, [])
    if len(pool) < need:
        print(f"  ⚠ {cat}: 华律网仅有 {len(pool):,} 条，不足 {need:,}，全部抽取")
        sample = pool
    else:
        sample = random.sample(pool, need)

    for obj in sample:
        sampled_questions.append({
            "category": cat,
            "hualv_title": obj.get("title", "").strip("[]"),
            "question": obj["question"],
            "area": obj.get("area", ""),
            "hualv_id": obj.get("hualv_id", ""),
        })
    print(f"  {cat}: 抽取 {len(sample):,} / {need:,} (池子 {len(pool):,})")

# ═══════════════════════════════════════════════════════════════
# 6. 输出文件
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  6. 写入文件")
print(f"{'='*70}")

# 6a. 最终保留的已有答案 (consultation_labeled → 筛选后)
retained = [d for d in labeled if d["id"] in keep_ids]
out_labeled = "data/sft/03_balanced/consultation_retained.jsonl"
with open(out_labeled, "w") as f:
    for d in retained:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
print(f"  保留答案: {out_labeled} ({len(retained):,} 条)")

# 6b. 待生成答案的华律网问题
out_questions = "data/sft/03_balanced/hualv_questions_to_label.jsonl"
with open(out_questions, "w") as f:
    for q in sampled_questions:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")
print(f"  待生成问题: {out_questions} ({len(sampled_questions):,} 条)")

# 6c. 降采样丢弃的数据（备查）
dropped = [d for d in labeled if d["id"] not in keep_ids]
out_dropped = "data/sft/03_balanced/consultation_dropped.jsonl"
with open(out_dropped, "w") as f:
    for d in dropped:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
print(f"  丢弃备查: {out_dropped} ({len(dropped):,} 条)")

# 6d. 采样方案总结 JSON
plan_summary = {
    "TARGET_N": TARGET_N,
    "CORE_RATIO": CORE_RATIO,
    "existing_total": existing_total,
    "retained": total_keep_final,
    "dropped": total_drop,
    "supplement_from_hualv": total_supplement,
    "final_size": total_keep_final + total_supplement,
    "per_category": {},
}
for cat in CATEGORIES:
    plan_summary["per_category"][cat] = {
        "target": target[cat],
        "existing": existing.get(cat, 0),
        "gap": gaps[cat],
        **supplement_plan[cat],
    }

out_plan = "data/sft/03_balanced/sft_balance_plan.json"
with open(out_plan, "w") as f:
    json.dump(plan_summary, f, ensure_ascii=False, indent=2)
print(f"  方案: {out_plan}")

print(f"\n  Done. 请确认方案后，用 LLM 为 {out_questions} 中的 {total_supplement:,} 个问题生成答案。")
