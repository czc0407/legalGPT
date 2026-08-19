#!/usr/bin/env python3
"""从华律网原始数据中扩充拒答偏好对。

扫描 hualv 清洗数据，找出需要拒答的问题（起草文书/审查合同/具体计算等），
用模板生成 chosen（礼貌拒答）和 rejected（硬答/回避），构造 DPO 偏好对。

用法:
    python scripts/phase3_data/build_refusal_pairs.py [--input data/sft/01_cleaned/hualv_question_clean.jsonl] [--output data/dpo/v0.2/card5_refusals_expanded.jsonl] [--n 200]
"""
import json, os, sys, re, random, argparse

# ── 拒答场景的正则模式 ──
REFUSAL_PATTERNS = [
    r'帮我写', r'写一份', r'起草', r'拟一份', r'拟订', r'拟定',
    r'帮我看看.*合同', r'审查.*合同', r'审核.*合同',
    r'帮我算', r'计算.*多少钱', r'计算.*赔偿',
    r'代理.*多少钱', r'请律师.*多少钱',
    r'怎么告', r'怎么起诉', r'怎么打官司',
    r'帮我改', r'修改.*合同',
]

# ── 礼貌拒答模板（chosen）──
REFUSAL_TEMPLATES = [
    "您好，我理解您的需求。但作为AI法律助手，我无法{action}，因为这需要执业律师结合您的具体情况来定制，以确保法律效力。不过，我可以帮您分析其中涉及的法律要点——比如{fallback}。如果您需要，我可以从这个角度为您提供参考。",
    "非常理解您需要{action_desc}。法律文书/代理服务需要专业人士在了解全部事实后提供，AI无法替代。我可以做的是帮您理清相关法律问题——比如{fallback}。您想了解哪方面？",
    "您提到的需求涉及专业的法律服务。我无法直接{action}，但可以帮您分析背后的法律关系——{fallback}。这能帮您在和律师沟通时更有方向。需要我展开分析吗？",
    "您好。{action_desc}这类事务需要执业律师根据您的具体情况处理，我作为AI不能替代。不过我可以帮您分析相关法律框架——{fallback}。这样您至少可以在找律师前理清思路。",
]

# ── 硬答/回避模板（rejected）──
REJECTED_TEMPLATES = [
    "根据相关法律规定，您需要向有管辖权的人民法院提起诉讼。建议您收集相关证据材料，包括书面合同、付款凭证、通讯记录等，然后委托专业律师代理诉讼。",
    "您提到的情况在司法实践中已有明确规定。根据法律规定，当事人应当通过协商、调解或诉讼等途径解决争议。建议您准备好相关材料，咨询当地律师。",
    "这是一个需要具体分析的法律问题。一般来说，法律对此类情况有相应的规定。建议您向专业律师咨询，以获取针对您具体情况的建议。",
    "法律对此类问题有明确的规定。当事人应当依法维护自身合法权益。具体到您的情况，建议通过法律途径解决，可以咨询当地法律援助机构。",
]

# ── 拒答场景 → 替代建议映射 ──
FALLBACK_ADVICE = {
    "协议": "协议的必备条款和风险点",
    "合同": "合同中的关键条款和常见陷阱",
    "起诉": "起诉的条件、流程和时效",
    "离婚": "离婚诉讼中财产分割和子女抚养的基本原则",
    "遗嘱": "遗嘱的法定形式和效力要件",
    "劳动": "劳动争议的处理流程和证据要求",
    "工伤": "工伤认定的条件和赔偿项目",
    "仲裁": "劳动仲裁的申请流程和时效",
    "房产": "房产交易中的法律风险和过户流程",
    "债务": "债务追讨的法律途径和诉讼时效",
}


def match_refusal(question: str) -> bool:
    """判断问题是否属于拒答场景。"""
    for pat in REFUSAL_PATTERNS:
        if re.search(pat, question):
            return True
    return False


def pick_fallback(question: str) -> str:
    """根据问题关键词选合适的替代建议。"""
    for key, advice in FALLBACK_ADVICE.items():
        if key in question:
            return advice
    return "相关法律的基本原则和注意事项"


def build_refusal_chosen(question: str) -> str:
    """生成礼貌拒答。"""
    template = random.choice(REFUSAL_TEMPLATES)
    fallback = pick_fallback(question)

    # 提取 action 描述
    if re.search(r'帮我写|写一份|起草|拟一份|拟订|拟定', question):
        action = "为您起草法律文书"
        action_desc = "起草法律文书"
    elif re.search(r'帮我看看.*合同|审查.*合同|审核.*合同|帮我改|修改.*合同', question):
        action = "为您审查合同"
        action_desc = "审查合同条款"
    elif re.search(r'帮我算|计算', question):
        action = "为您计算具体金额"
        action_desc = "精确计算赔偿或费用"
    elif re.search(r'代理|请律师|怎么告|怎么起诉|怎么打官司', question):
        action = "为您提供诉讼代理"
        action_desc = "提供诉讼代理服务"
    else:
        action = "直接为您提供该项法律服务"
        action_desc = "这项法律服务"

    return template.format(action=action, action_desc=action_desc, fallback=fallback)


def build_refusal_rejected() -> str:
    """生成硬答（拒绝失败）。"""
    return random.choice(REJECTED_TEMPLATES)


def main():
    parser = argparse.ArgumentParser(description="扩充拒答偏好对")
    parser.add_argument("--input", default="data/sft/01_cleaned/hualv_question_clean.jsonl")
    parser.add_argument("--output", default="data/dpo/v0.2/card5_refusals_expanded.jsonl")
    parser.add_argument("--n", type=int, default=200, help="目标数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    if not os.path.exists(args.input):
        print(f"❌ 输入文件不存在: {args.input}")
        sys.exit(1)

    # 扫描候选问题
    print(f"扫描: {args.input}")
    candidates = []
    with open(args.input) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                q = item.get("question", "") or item.get("title", "")
            except (json.JSONDecodeError, AttributeError):
                # 可能是纯文本，每行一个问题
                q = line.strip()

            if match_refusal(q) and len(q) >= 10 and len(q) <= 200:
                candidates.append(q)

    print(f"候选问题: {len(candidates)} 条")

    if len(candidates) < args.n:
        print(f"⚠️ 候选不足 {args.n}，使用全部 {len(candidates)} 条")
        n = len(candidates)
    else:
        n = args.n

    selected = random.sample(candidates, n)

    # 去重
    seen = set()
    pairs = []
    for q in selected:
        if q in seen:
            continue
        seen.add(q)
        chosen = build_refusal_chosen(q)
        rejected = build_refusal_rejected()
        if len(chosen) >= 50 and len(rejected) >= 50 and chosen != rejected:
            pairs.append({
                "instruction": "你是一名中国法律专家。",
                "input": q,
                "chosen": chosen,
                "rejected": rejected,
            })

    # 输出
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"生成: {len(pairs)} 对 → {args.output}")
    # 基本校验
    errors = sum(1 for p in pairs if p["chosen"] == p["rejected"] or len(p["rejected"]) < 50)
    print(f"校验: {'✅ 通过' if errors == 0 else f'❌ {errors} 条有问题'}")
    print(f"\n样例:")
    print(f"  Q: {pairs[0]['input'][:80]}")
    print(f"  chosen: {pairs[0]['chosen'][:100]}...")
    print(f"  rejected: {pairs[0]['rejected'][:100]}...")


if __name__ == "__main__":
    main()
