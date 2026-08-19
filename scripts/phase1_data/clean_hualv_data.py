#!/usr/bin/env python3
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
"""
清洗华律网 question_2.json：
  1. 文本去重 — simhash 近重复检测
  2. 长度/信息量过滤 — 过短、无案情描述
  3. 广告/无关内容过滤 — 关键词黑名单

输出清洗后的全量池子 (JSONL) + 统计报告。
"""

import json
import re
import time
from collections import Counter
from simhash import Simhash

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
INPUT = "data/external/question_2.json"
OUTPUT = "data/sft/01_cleaned/hualv_question_clean.jsonl"
REPORT = "data/reports/hualv_cleaning_report.json"

MIN_QUESTION_LEN = 15           # 最短问题长度（字符）
SIMHASH_HAMMING = 4             # simhash 汉明距离阈值 (越小越严格)
MAX_QUESTION_LEN = 500          # 最长问题长度

# 广告/无关关键词 (只要在问题中出现即过滤)
AD_KEYWORDS = [
    "微信", "微信号", "QQ群", "加Q", "加我", "扫码", "二维码",
    "热线电话", "免费咨询", "联系电话", "手机号", "拨打",
    "推广", "广告", "测试数据", "测试问题", "test",
    "http://", "https://", "www.",
    "点击", "关注", "转发", "点赞",
    "代写", "代发论文", "办证", "发票",
    "刷单", "兼职打字", "日赚", "月入",
    "充值", "提现", "返利", "注册送",
]

# 无信息量的纯问句模板 (整句匹配, 非子串)
GENERIC_TEMPLATES = [
    "怎么办", "怎么办啊", "怎么办？", "怎么办啊？",
    "我该怎么办", "我该怎么办？", "我该怎么办啊",
    "请问怎么办", "请问我该怎么办",
    "怎么处理", "怎么处理？", "怎么解决", "怎么解决？",
    "求助", "求助！", "帮帮我", "帮帮我！",
    "有人吗", "有人在吗", "在线等", "急急急",
    "法律咨询", "我要咨询", "我需要咨询",
    "请回答", "请问一下", "问一下", "想咨询一下",
    "咨询个问题", "咨询一个问题",
]


def normalize(text):
    """基础归一化: 全角→半角标点, 去多余空白"""
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def is_noise_question(text):
    """过滤规则, 返回 (is_bad, reason)"""
    t = text.strip()

    # 1. 长度
    if len(t) < MIN_QUESTION_LEN:
        return True, f"过短({len(t)}字)"
    if len(t) > MAX_QUESTION_LEN:
        return True, f"过长({len(t)}字)"

    # 2. 纯标点/数字/字母
    if re.match(r'^[\d\s\W_]+$', t):
        return True, "纯符号/数字"

    # 3. 重复字符 > 80%
    if len(t) > 0:
        most_common_ratio = Counter(t).most_common(1)[0][1] / len(t)
        if most_common_ratio > 0.8:
            return True, "字符重复度高"

    # 4. 无信息模板
    if t in GENERIC_TEMPLATES:
        return True, "通用无信息模板"

    # 5. 广告关键词
    for kw in AD_KEYWORDS:
        if kw in t:
            return True, f"广告词: {kw}"

    # 6. 过短且无实质名词 (至少要有具体事物)
    if len(t) <= 30:
        # 检查是否有足够的中文汉字
        hanzi = len(re.findall(r'[一-鿿]', t))
        if hanzi < 6:
            return True, f"汉字太少({hanzi}个)"

    return False, ""


# ═══════════════════════════════════════════════════════════════
# 阶段 1: 规则过滤 + 精确去重
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("  阶段 1: 规则过滤 + 精确去重")
print("=" * 60)

seen_exact = set()
total = 0
rule_filtered = Counter()
exact_dup = 0
passed_stage1 = []  # (question_text, obj)

with open(INPUT) as f:
    for line in f:
        if not line.strip():
            continue
        total += 1
        obj = json.loads(line)
        q = normalize(obj.get("question", ""))
        if not q:
            rule_filtered["空问题"] += 1
            continue

        is_bad, reason = is_noise_question(q)
        if is_bad:
            rule_filtered[reason] += 1
            continue

        # 精确去重
        if q in seen_exact:
            exact_dup += 1
            continue
        seen_exact.add(q)

        passed_stage1.append((q, obj))

print(f"  原始总量:     {total:>10,}")
print(f"  规则过滤:     {sum(rule_filtered.values()):>10,}")
for reason, cnt in rule_filtered.most_common(15):
    print(f"    - {reason:<20s} {cnt:>8,}")
print(f"  精确去重:     {exact_dup:>10,}")
print(f"  阶段1后保留:  {len(passed_stage1):>10,}")

# ═══════════════════════════════════════════════════════════════
# 阶段 2: Simhash 近重复检测
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  阶段 2: Simhash 近重复检测 (汉明距离 ≤ {SIMHASH_HAMMING})")
print(f"{'='*60}")

t0 = time.time()

# 批量计算 simhash
print(f"  计算 {len(passed_stage1):,} 条 simhash...")
hashes = []
for i, (q, obj) in enumerate(passed_stage1):
    h = Simhash(q)
    hashes.append((h, i))
    if (i + 1) % 100000 == 0:
        print(f"    {i+1:,} / {len(passed_stage1):,}")

# 按 simhash 值排序，滑动窗口检测
print("  排序并检测近重复...")
hashes.sort(key=lambda x: x[0].value)

keep_indices = set(range(len(passed_stage1)))
simhash_dup = 0
window_size = 200  # 每侧检查 200 个邻居

for i, (h, idx) in enumerate(hashes):
    # 检查右侧窗口内的邻居
    for j in range(i + 1, min(i + window_size + 1, len(hashes))):
        h2, idx2 = hashes[j]
        if h.distance(h2) <= SIMHASH_HAMMING:
            # 保留先出现的 (sorted order 中靠前的)
            if idx2 in keep_indices:
                keep_indices.discard(idx2)
                simhash_dup += 1

    if (i + 1) % 100000 == 0:
        print(f"    {i+1:,} / {len(hashes):,}  已标注重复: {simhash_dup:,}")

t1 = time.time()

print(f"\n  Simhash 去重:   {simhash_dup:>10,}")
print(f"  阶段2后保留:    {len(keep_indices):>10,}")
print(f"  耗时:           {t1 - t0:.1f}s")

# ═══════════════════════════════════════════════════════════════
# 阶段 3: 输出清洗后数据
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  阶段 3: 输出")
print(f"{'='*60}")

from taxonomy_config import LABEL_REMAP

kept_qs = []  # (question_text, original_obj)
for i, (q, obj) in enumerate(passed_stage1):
    if i in keep_indices:
        kept_qs.append((q, obj))

# 按原标签统计
label_dist = Counter()
with open(OUTPUT, "w") as f:
    for q, obj in kept_qs:
        title = obj.get("title", "").strip("[]")
        if title in LABEL_REMAP:
            l1, _, _ = LABEL_REMAP[title]
        else:
            l1 = title
        label_dist[l1] += 1

        out = {
            "hualv_id": obj["_id"]["$oid"] if isinstance(obj.get("_id"), dict) else str(obj.get("_id", "")),
            "title": obj.get("title", ""),
            "question": q,
            "area": obj.get("area", ""),
            "category_l1": l1,
        }
        f.write(json.dumps(out, ensure_ascii=False) + "\n")

print(f"  输出: {OUTPUT}")
print(f"  保留: {len(kept_qs):,} / {total:,} ({len(kept_qs)/total*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════════════
report = {
    "input": INPUT,
    "input_total": total,
    "rule_filtered_total": sum(rule_filtered.values()),
    "rule_filtered_detail": dict(rule_filtered.most_common()),
    "exact_duplicates": exact_dup,
    "simhash_duplicates": simhash_dup,
    "simhash_hamming_threshold": SIMHASH_HAMMING,
    "simhash_time_s": round(t1 - t0, 1),
    "output_total": len(kept_qs),
    "output_path": OUTPUT,
    "label_distribution": dict(label_dist.most_common()),
}

with open(REPORT, "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"  报告: {REPORT}")

# 终端摘要
print(f"\n{'='*60}")
print(f"  清洗汇总")
print(f"{'='*60}")
print(f"  原始:        {total:>10,}")
print(f"  规则过滤:    {sum(rule_filtered.values()):>10,}")
print(f"  精确去重:    {exact_dup:>10,}")
print(f"  Simhash去重: {simhash_dup:>10,}")
print(f"  ─────────────────────")
print(f"  最终保留:    {len(kept_qs):>10,} ({len(kept_qs)/total*100:.1f}%)")
print(f"\n  Done.")
