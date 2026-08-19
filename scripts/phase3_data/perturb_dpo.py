#!/usr/bin/env python3
"""阶段三 · DPO 扰动器。按 spec §4.2 算法生成 rejected。

用法:
    python scripts/phase3_data/perturb_dpo.py [--input data/sft/04_cards/] [--output data/dpo/v0.1/]
"""
from __future__ import annotations
import json, os, sys, re, random, argparse
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, PROJECT_DIR)

from dpo_assets import CONFUSION_PAIRS, FAKE_LAW_NAMES, HEDGING_PHRASES

INSTRUCTION = "你是一名中国法律专家。"

RETAINED_FILE = "data/sft/03_balanced/consultation_retained.jsonl"

# ═══════════════════════════════════════════════════════════════
# 扰动算法
# ═══════════════════════════════════════════════════════════════

def perturb_p3(answer: str) -> str | None:
    """P3 法律依据幻觉：替换法律名称。"""
    laws = re.findall(r'《([^》]+)》', answer)
    if not laws:
        return None
    # 优先查混淆对表
    for law in laws:
        key = f"《{law}》"
        if key in CONFUSION_PAIRS:
            return answer.replace(key, CONFUSION_PAIRS[key])
    # 回退到假名池
    fake = random.choice(FAKE_LAW_NAMES)
    target = f"《{random.choice(laws)}》"
    return answer.replace(target, fake, 1)


# P6 绝对化措辞池（多样化，解决 Round 1 的"80% 同结尾"模板化问题）
_ABSOLUTE_TAILS = [
    "根据相关法律规定，您一定能获得相应的赔偿。",
    "依据法律规定，您的诉求完全成立，必定得到支持。",
    "本案事实清楚、证据充分，您必定能够胜诉。",
    "从法律角度看，您的情况必然能够得到有利的处理结果。",
    "法律对此有明确规定，您完全有权利获得相应的赔偿和补偿。",
    "综合来看，您的权利受到明确保护，必定能够维权成功。",
    "根据现行法律，对方的行为已经构成违法，您肯定能获得赔偿。",
    "法律明确支持您的主张，您一定能得到满意的结果。",
]


def perturb_p6(answer: str) -> str | None:
    """P6 过度确定性：条件化→绝对化。"""
    conditionals = re.findall(r'如果[^，。；]*?[,，。；]', answer)
    if conditionals:
        target = random.choice(conditionals)
        replacement = target.replace("如果", "").replace("可能", "肯定").replace("或许", "必然")
        result = answer.replace(target, replacement, 1)
        # 追加绝对化措辞（多样化）
        if "一定" not in result and "肯定" not in result:
            result = result.rstrip() + "\n\n" + random.choice(_ABSOLUTE_TAILS)
        return result
    # 软化→硬化：文末追加绝对化（多样化）
    if "一定" not in answer and "肯定" not in answer and "必然" not in answer:
        return answer.rstrip() + "\n\n" + random.choice(_ABSOLUTE_TAILS)
    return None


def perturb_p6_refusal(answer: str, question: str) -> str | None:
    """P6-Refusal 拒答失败：将礼貌拒答替换为硬给回答。

    针对卡 5（拒答样本），模型应当拒答但 SFT 训练后仍可能在该拒答时硬答。
    此扰动生成一个"硬答"作为 rejected——模型避开了用户真正的需求，
    转而给出一个无关的法律定义或泛泛的一般性回答。
    """
    # 从 DISC 知识 QA 短定义池中选一个，模拟"问了不该问的却硬答"
    fake_answers = [
        "根据相关法律规定，这是一个需要具体分析的法律问题。法律对此有明确规定，具体情况需要结合实际案情进行判断。建议您收集相关证据材料后，向专业律师或法律服务机构寻求帮助。",
        "您提出的这个问题涉及法律领域的专业知识。根据法律法规的规定，相关权利和义务需要依据具体事实来认定。建议您准备好相关材料，咨询当地律师或法律援助机构。",
        "法律对此类问题有明确的规定。根据相关法律，当事人应当依法行使权利、履行义务。具体到您的情况，建议您向有关部门或专业律师咨询，以获取针对性的法律意见。",
        "这个问题需要结合具体事实来判断。一般而言，法律会从多个角度综合考量。由于您提供的信息有限，无法给出确切的法律意见，建议您进一步补充相关细节或咨询专业人士。",
    ]
    # 50% 概率返回通用硬答，50% 概率基于问题关键词给出看起来"相关"但实际回避核心的回答
    if random.random() < 0.5 or not question.strip():
        return random.choice(fake_answers)
    # 否则，构造一个"看起来在回答但实际上回避了核心需求"的 rejected
    rejections = [
        f"根据相关法律，您提到的这个问题在司法实践中已有明确的规定。建议您收集相关证据，向有管辖权的法院提起诉讼。",
        f"您提到的情况，根据法律规定，应当先进行协商，协商不成可以向人民法院起诉。建议您准备好相关材料。",
        f"对于这个问题，法律有相应的规定。一般来说，当事人可以通过协商、调解、仲裁、诉讼等途径解决。",
    ]
    return random.choice(rejections)


def perturb_p5(answer: str) -> str | None:
    """P5 建议空泛：替换建议段落为套话。"""
    # 找建议段（最后一段或以"建议"开头的段落）
    paras = answer.split('\n\n')
    for i in range(len(paras) - 1, -1, -1):
        if '建议' in paras[i] and len(paras[i]) > 20:
            paras[i] = random.choice(HEDGING_PHRASES)
            return '\n\n'.join(paras)
    return None


def perturb_p2(answer: str) -> str | None:
    """P2 格式不规范：插入标签词。"""
    paras = [p for p in answer.split('\n\n') if p.strip()]
    if len(paras) < 3:
        return None
    labels = ["首先", "其次", "再次", "最后"]
    for i in range(min(len(paras), len(labels))):
        if not paras[i].startswith(labels[i]):
            paras[i] = f"{labels[i]}，{paras[i]}"
    return '\n\n'.join(paras)


def perturb_p4(answer: str, question: str) -> str | None:
    """P4 编造事实：在'理解处境'段前插入编造。

    修复 Round 1 的错配问题：原来关键词匹配不上就随机选模板，
    导致"自愿离职"匹配到"货款诈骗"。现在扩展关键词 + 匹配不上则不扰动。
    """
    fabricated_details = [
        (["交通", "车祸", "追尾", "闯红灯", "撞", "事故"], "您在闯红灯时发生了追尾事故，对方车辆受损严重，"),
        (["工资", "欠薪", "拖欠", "加班", "劳动报酬", "辞退"], "您已被拖欠工资超过六个月，公司明确表示拒绝支付，"),
        (["工伤", "工地", "受伤", "伤残", "骨折"], "您在工地受伤后当场昏迷，被送往医院住院治疗两周，"),
        (["离婚", "抚养", "出轨", "家暴", "财产分割"], "对方已搬离家庭住所超过一年，期间从未支付子女抚养费，"),
        (["合同", "货款", "违约金", "协议", "定金"], "对方在收到货款后立即注销了公司账户并变更了法定代表人，"),
    ]
    for keywords, detail in fabricated_details:
        if any(kw in question for kw in keywords):
            return detail + answer
    return None  # 匹配不上则不扰动，避免错配


def check_valid(rejected: str, chosen: str) -> bool:
    """验收红线上规定的检查。"""
    if not rejected or len(rejected) < 50:
        return False
    if rejected == chosen:
        return False
    return True

# ═══════════════════════════════════════════════════════════════
# 天然 rejected（DISC/zixun 原始回答）
# ═══════════════════════════════════════════════════════════════

def extract_natural_rejected():
    """从 retained 数据中提取 DISC/zixun 原始回答作为 rejected。"""
    if not os.path.exists(RETAINED_FILE):
        print(f"  警告: {RETAINED_FILE} 不存在，跳过天然 rejected")
        return []

    with open(RETAINED_FILE) as f:
        retained = [json.loads(l) for l in f if l.strip()]

    pairs = []
    for r in retained:
        source = r.get("source", "")
        response = r.get("response", "")
        question = r.get("query") or r.get("question", "")
        if not response or not question:
            continue
        if source == "DISC-Law-SFT":
            pairs.append({"question": question, "rejected": response, "pain_point": "P1+P2", "source": "disc_natural"})
        elif source == "zixun_gpt4":
            pairs.append({"question": question, "rejected": response, "pain_point": "P2+P5+P6", "source": "zixun_natural"})
    print(f"  天然 rejected: {len(pairs)} 对 (DISC={sum(1 for p in pairs if 'disc' in p['source'])}, zixun={sum(1 for p in pairs if 'zixun' in p['source'])})")
    return pairs

# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def perturb_all(raw_dir: str, output_dir: str, skip_cards: set = frozenset()):
    os.makedirs(output_dir, exist_ok=True)

    # 抽样比例（按卡）：控制偏好对总量，避免爆炸
    card_rates = {
        1: 0.10,   # 信息充足 → P3，~370 对
        2: 1.00,   # 信息不足 → P6+P4 多 rejected，全量
        3: 0.05,   # DISC → P2 + 天然，~130 对
        4: 0.30,   # zixun → P2+P5 + 天然，~100 对
        5: 1.00,   # 拒答 → P6-Refusal，全量
        6: 0.00,   # 知识 QA → Round 1 不扰动
    }

    # 加载所有 raw 样本
    all_raw = []
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.startswith("card") or not fname.endswith(".jsonl"):
            continue
        if "progress" in fname:
            continue
        with open(os.path.join(raw_dir, fname)) as f:
            for line in f:
                if line.strip():
                    all_raw.append(json.loads(line))

    print(f"raw 样本: {len(all_raw)} 条")

    # 程序注入 rejected
    injected = []
    # 扰动器注册：(名称, 函数, 适用卡集合)
    perturb_registry = [
        ("P3", perturb_p3, {1}),
        ("P6", perturb_p6, {1, 4}),       # 卡 2/5 在下面单独处理
        ("P5", perturb_p5, {1, 4}),
        ("P2", perturb_p2, {3, 4}),
    ]

    stats = defaultdict(int)
    for raw in all_raw:
        answer = raw.get("answer", "")
        question = raw.get("question", "")
        card = raw.get("card", 0)
        if not answer:
            continue

        # 跳过指定卡（卡 2 审慎度 / 卡 5 拒答 已单独生成）
        if card in skip_cards:
            continue

        # 按卡抽样
        rate = card_rates.get(card, 1.0)
        if rate < 1.0 and random.random() >= rate:
            continue

        # ── 卡 5 专属：P6-Refusal（拒答失败）──
        if card == 5:
            rejected = perturb_p6_refusal(answer, question)
            if rejected and check_valid(rejected, answer):
                injected.append({
                    "instruction": INSTRUCTION,
                    "input": question,
                    "chosen": answer,
                    "rejected": rejected,
                })
                stats["P6-Refusal"] += 1
            continue

        # ── 卡 2 多 rejected：P6 + P4 各一对 ──
        if card == 2:
            rej_p6 = perturb_p6(answer)
            if rej_p6 and check_valid(rej_p6, answer):
                injected.append({
                    "instruction": INSTRUCTION,
                    "input": question,
                    "chosen": answer,
                    "rejected": rej_p6,
                })
                stats["P6"] += 1
            rej_p4 = perturb_p4(answer, question)
            if rej_p4 and check_valid(rej_p4, answer):
                injected.append({
                    "instruction": INSTRUCTION,
                    "input": question,
                    "chosen": answer,
                    "rejected": rej_p4,
                })
                stats["P4"] += 1
            continue

        # ── 其他卡：从适用扰动器中随机选一个 ──
        candidates = []
        for p_name, p_func, valid_cards in perturb_registry:
            if card in valid_cards:
                candidates.append((p_name, p_func))
        if not candidates:
            continue
        p_name, p_func = random.choice(candidates)
        rejected = p_func(answer) if p_name != "P4" else perturb_p4(answer, question)
        if rejected and check_valid(rejected, answer):
            injected.append({
                "instruction": INSTRUCTION,
                "input": question,
                "chosen": answer,
                "rejected": rejected,
            })
            stats[p_name] += 1

    print(f"\n  程序注入: {len(injected)} 对")
    for k, v in sorted(stats.items()):
        print(f"    {k}: {v}")

    # 天然 rejected
    natural = extract_natural_rejected()
    # 匹配 chosen（用同一 question 从 raw 中找）
    natural_pairs = []
    raw_by_question = {}
    for r in all_raw:
        q = r.get("question", "")
        if q:
            raw_by_question[q] = r.get("answer", "")

    for n in natural:
        chosen = raw_by_question.get(n["question"], "")
        if chosen and chosen != n["rejected"] and len(n["rejected"]) >= 50:
            natural_pairs.append({
                "instruction": INSTRUCTION,
                "input": n["question"],
                "chosen": chosen,
                "rejected": n["rejected"],
                "source": n.get("source", ""),           # disc_natural / zixun_natural
                "pain_point": n.get("pain_point", ""),   # P1+P2 / P2+P5+P6
            })

    # 天然 rejected 抽样（DISC 5%, zixun 30%，避免过量）
    random.shuffle(natural_pairs)
    sampled_natural = []
    disc_count = 0
    zixun_count = 0
    for np in natural_pairs:
        source_key = "disc" if "disc" in np.get("source", "") else "zixun"
        if source_key == "disc" and disc_count < 130:  # 5% of 2696
            sampled_natural.append(np)
            disc_count += 1
        elif source_key == "zixun" and zixun_count < 100:  # 30% of 338
            sampled_natural.append(np)
            zixun_count += 1

    print(f"  天然 rejected 匹配: {len(natural_pairs)} 对 → 抽样后: {len(sampled_natural)} 对 (DISC={disc_count}, zixun={zixun_count})")

    # 合并输出（仅保留 LLaMA-Factory DPO 格式四字段）
    all_dpo = injected + sampled_natural
    output_file = os.path.join(output_dir, "train.jsonl")
    dpo_fields = {"instruction", "input", "chosen", "rejected"}
    with open(output_file, "w") as f:
        for d in all_dpo:
            clean = {k: d[k] for k in dpo_fields}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")

    print(f"\n  总计: {len(all_dpo)} 对 → {output_file}")

    # Level 3 校验
    errors = 0
    for d in all_dpo:
        if d["chosen"] == d["rejected"]:
            errors += 1
        if len(d["rejected"]) < 50:
            errors += 1
    print(f"  Level 3 校验: {'✅ 通过' if errors == 0 else f'❌ {errors} 条有问题'}")

def main():
    parser = argparse.ArgumentParser(description="DPO 扰动器")
    parser.add_argument("--input", default="data/sft/04_cards/")
    parser.add_argument("--output", default="data/dpo/v0.1/")
    parser.add_argument("--skip-cards", default="", help="跳过的卡，逗号分隔，如 2,5")
    args = parser.parse_args()
    skip_cards = {int(c) for c in args.skip_cards.split(",") if c.strip()}
    perturb_all(args.input, args.output, skip_cards)

if __name__ == "__main__":
    main()
