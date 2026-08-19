#!/usr/bin/env python3
"""阶段三 · 拒答样本生成器。按 Prompt D 参数化生成约 100 条拒答样本。

用法:
    python scripts/phase3_data/build_refusals.py --smoke   # 小样冒烟（10 条）
    python scripts/phase3_data/build_refusals.py --full     # 全量生成（~100 条）
"""
import json, os, sys, time, random, argparse
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from openai import OpenAI
from llm_config import OPENKEY_API_KEY, OPENKEY_API_BASE, MAX_RETRIES, SLEEP_BETWEEN
from sft_prompts import PROMPT_D_SYSTEM, PROMPT_D_USER

MODEL_NAME = "deepseek-chat"
GEN_MAX_TOKENS = 300
TEMPERATURE = 0.3
RAW_DIR = "data/sft/04_cards"

# ═══════════════════════════════════════════════════════════════
# 场景参数池：4 场景 × ~25 个不同 user_input = ~100 条
# 每个场景只调一次 API，多样性来自不同输入而非温度
# ═══════════════════════════════════════════════════════════════

REFUSAL_SCENARIOS = [
    # ═══ 场景 A: 文书起草 ═══
    {"scenario_type": "文书起草", "specific_topic": "离婚起诉状", "user_input": "帮我写一份离婚起诉状"},
    {"scenario_type": "文书起草", "specific_topic": "劳动仲裁申请书", "user_input": "帮我写一份劳动仲裁申请书"},
    {"scenario_type": "文书起草", "specific_topic": "房屋买卖合同", "user_input": "我要卖房子，帮我拟一份房屋买卖合同"},
    {"scenario_type": "文书起草", "specific_topic": "遗嘱", "user_input": "我想立一份遗嘱，帮我写一下"},
    {"scenario_type": "文书起草", "specific_topic": "借条模板", "user_input": "朋友借我钱，帮我写一张有法律效力的借条"},
    {"scenario_type": "文书起草", "specific_topic": "起诉状格式", "user_input": "我要去法院起诉，起诉状怎么写？给我个模板"},
    {"scenario_type": "文书起草", "specific_topic": "租赁合同", "user_input": "我要租房，帮我起草一份租赁合同"},
    {"scenario_type": "文书起草", "specific_topic": "合作协议", "user_input": "我和朋友合伙开店，帮我写一份合作协议"},
    {"scenario_type": "文书起草", "specific_topic": "授权委托书", "user_input": "我要委托别人帮我处理房产过户，帮我写一份授权委托书"},
    {"scenario_type": "文书起草", "specific_topic": "答辩状", "user_input": "我被起诉了，帮我写一份答辩状"},
    {"scenario_type": "文书起草", "specific_topic": "强制执行申请", "user_input": "我官司赢了但对方不给钱，帮我写一份强制执行申请书"},
    {"scenario_type": "文书起草", "specific_topic": "工伤认定申请", "user_input": "帮我在线填一下工伤认定申请表"},
    {"scenario_type": "文书起草", "specific_topic": "仲裁申请书", "user_input": "公司欠薪，我要去仲裁，帮我写仲裁申请书"},
    {"scenario_type": "文书起草", "specific_topic": "证据清单", "user_input": "帮我列一份打官司要准备的证据清单"},
    {"scenario_type": "文书起草", "specific_topic": "保全申请", "user_input": "对方在转移财产，帮我申请财产保全，申请书帮我写"},
    {"scenario_type": "文书起草", "specific_topic": "上诉状", "user_input": "一审败诉了，帮我写一份上诉状"},
    {"scenario_type": "文书起草", "specific_topic": "婚前协议", "user_input": "我要结婚，帮我拟一份婚前财产协议"},
    {"scenario_type": "文书起草", "specific_topic": "商标注册申请", "user_input": "帮我填写商标注册申请材料"},
    {"scenario_type": "文书起草", "specific_topic": "公司章程", "user_input": "我要注册公司，帮我写一份公司章程"},
    {"scenario_type": "文书起草", "specific_topic": "商标转让协议", "user_input": "我要把商标转让给别人，帮我写转让协议"},
    {"scenario_type": "文书起草", "specific_topic": "竞业限制协议", "user_input": "我是老板，帮我写一份员工竞业限制协议"},
    {"scenario_type": "文书起草", "specific_topic": "保密协议", "user_input": "我们公司要和供应商签保密协议，帮我起草一份"},
    {"scenario_type": "文书起草", "specific_topic": "退租通知", "user_input": "帮我写一份提前退租的书面通知给房东"},
    {"scenario_type": "文书起草", "specific_topic": "工伤赔偿协议", "user_input": "老板愿意私了工伤赔偿，帮我拟一份赔偿协议"},
    {"scenario_type": "文书起草", "specific_topic": "股权转让协议", "user_input": "我要把公司股份转让给合伙人，帮我写协议"},

    # ═══ 场景 B: 实时信息查询 ═══
    {"scenario_type": "实时查询", "specific_topic": "工伤赔偿标准", "user_input": "2024 年最新的工伤赔偿标准是多少？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "深圳最低工资", "user_input": "2024 年深圳最低工资标准现在是多少"},
    {"scenario_type": "实时查询", "specific_topic": "新交规变化", "user_input": "今年新交规有什么变化？网上说的靠不靠谱"},
    {"scenario_type": "实时查询", "specific_topic": "南山法院立案", "user_input": "深圳南山法院立案现在需要什么材料？流程是怎样的"},
    {"scenario_type": "实时查询", "specific_topic": "北京社保基数", "user_input": "2024 年北京社保缴费基数上下限是多少？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "上海公积金政策", "user_input": "上海公积金最新的提取政策是什么？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "个人所得税税率", "user_input": "2024 年最新的个人所得税税率表是什么"},
    {"scenario_type": "实时查询", "specific_topic": "广州购房资格", "user_input": "广州现在买房需要什么资格？限购政策是怎样的"},
    {"scenario_type": "实时查询", "specific_topic": "杭州车牌摇号", "user_input": "杭州车牌摇号的中签率现在是多少"},
    {"scenario_type": "实时查询", "specific_topic": "武汉落户政策", "user_input": "武汉现在的积分落户政策是怎样的？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "成都购房补贴", "user_input": "成都现在买房有政府补贴吗？补贴标准是多少"},
    {"scenario_type": "实时查询", "specific_topic": "养老保险领取", "user_input": "2024 年退休能领多少养老金？帮我算一下"},
    {"scenario_type": "实时查询", "specific_topic": "医保报销比例", "user_input": "北京职工医保的报销比例现在是多少"},
    {"scenario_type": "实时查询", "specific_topic": "房产税政策", "user_input": "房产税现在开始征收了吗？税率是多少"},
    {"scenario_type": "实时查询", "specific_topic": "小额诉讼标的额", "user_input": "2024 年小额诉讼的标的额上限是多少"},
    {"scenario_type": "实时查询", "specific_topic": "征信修复政策", "user_input": "现在征信有逾期记录怎么修复？有什么新政策吗"},
    {"scenario_type": "实时查询", "specific_topic": "电动车新规", "user_input": "现在电动车需要驾照吗？最新规定是什么"},
    {"scenario_type": "实时查询", "specific_topic": "生育津贴标准", "user_input": "2024 年生育津贴能领多少？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "法律援助条件", "user_input": "现在申请免费法律援助需要什么条件"},
    {"scenario_type": "实时查询", "specific_topic": "专利年费标准", "user_input": "发明专利的年费现在多少钱？帮我查一下"},
    {"scenario_type": "实时查询", "specific_topic": "房屋维修基金", "user_input": "房屋维修基金现在怎么用？需要什么条件"},
    {"scenario_type": "实时查询", "specific_topic": "北京公租房申请", "user_input": "北京公租房现在怎么申请？排队要多久"},
    {"scenario_type": "实时查询", "specific_topic": "个税专项扣除", "user_input": "2024 年个税专项附加扣除标准变了吗"},
    {"scenario_type": "实时查询", "specific_topic": "海南自贸港税收", "user_input": "海南自贸港现在有什么税收优惠政策"},
    {"scenario_type": "实时查询", "specific_topic": "二手房交易税费", "user_input": "现在二手房买卖要交多少税？帮我算一下"},

    # ═══ 场景 C: 需要执业资质的判断 ═══
    {"scenario_type": "执业资质", "specific_topic": "离婚胜算", "user_input": "我的案子有多少胜算？能帮我分析一下吗"},
    {"scenario_type": "执业资质", "specific_topic": "合同风险判断", "user_input": "帮我看看这份合同有什么法律风险，我应该签吗"},
    {"scenario_type": "执业资质", "specific_topic": "交通事故索赔", "user_input": "我被车撞了，帮我算一下应该索赔多少钱"},
    {"scenario_type": "执业资质", "specific_topic": "股权纠纷预判", "user_input": "我和合伙人闹翻了，你觉得法院会怎么判"},
    {"scenario_type": "执业资质", "specific_topic": "劳动仲裁胜率", "user_input": "公司无故辞退我，我申请仲裁赢的概率大吗"},
    {"scenario_type": "执业资质", "specific_topic": "工伤等级判断", "user_input": "我手指骨折了，你觉得能评几级工伤"},
    {"scenario_type": "执业资质", "specific_topic": "拆迁补偿评估", "user_input": "我家要拆迁了，你觉得应该赔多少才合理"},
    {"scenario_type": "执业资质", "specific_topic": "遗产分配预判", "user_input": "我爸没留遗嘱，财产会怎么分？帮我分析"},
    {"scenario_type": "执业资质", "specific_topic": "商铺转让合法性", "user_input": "我想转租店铺但要房东同意，你看我这样操作行不行"},
    {"scenario_type": "执业资质", "specific_topic": "竞业限制效力", "user_input": "公司让我签了竞业限制，这个条款有效吗？会被执行吗"},
    {"scenario_type": "执业资质", "specific_topic": "刑事立案可能性", "user_input": "我报案了对方诈骗我 50 万，你说警察能立案吗"},
    {"scenario_type": "执业资质", "specific_topic": "取保候审可能性", "user_input": "我朋友被抓了，你觉得能办取保候审吗"},
    {"scenario_type": "执业资质", "specific_topic": "连带责任判断", "user_input": "我给人做了担保那个人不还钱了，我要承担多少责任"},
    {"scenario_type": "执业资质", "specific_topic": "试用期合法性", "user_input": "公司跟我签了 6 个月试用期，这合法吗"},
    {"scenario_type": "执业资质", "specific_topic": "加班费计算", "user_input": "帮我算一下我这两年加班该拿多少加班费"},
    {"scenario_type": "执业资质", "specific_topic": "性骚扰认定", "user_input": "领导总在工作群里发暧昧消息，这算性骚扰吗"},
    {"scenario_type": "执业资质", "specific_topic": "房屋漏水责任", "user_input": "楼上漏水我家泡了，你看损失应该怎么算"},
    {"scenario_type": "执业资质", "specific_topic": "网络诈骗追回", "user_input": "我被网络诈骗骗了 20 万，钱能追回来吗"},
    {"scenario_type": "执业资质", "specific_topic": "借条效力", "user_input": "朋友在微信里说欠我钱，这个聊天记录能当借条用吗"},
    {"scenario_type": "执业资质", "specific_topic": "征信影响", "user_input": "我欠了网贷不还会影响征信吗？会不会被起诉"},
    {"scenario_type": "执业资质", "specific_topic": "直播间纠纷", "user_input": "我在直播间买的东西是假货，你觉得能退一赔三吗"},
    {"scenario_type": "执业资质", "specific_topic": "宠物伤人", "user_input": "邻居的狗把我孩子咬了，医药费和赔偿该怎么算"},
    {"scenario_type": "执业资质", "specific_topic": "房贷提前还", "user_input": "我想提前还房贷，你看合算吗？违约金怎么算"},
    {"scenario_type": "执业资质", "specific_topic": "过户税费", "user_input": "父母把房子过户给我要交多少税？哪种方式最省钱"},
    {"scenario_type": "执业资质", "specific_topic": "离婚财产分割", "user_input": "我老公在外有私生子，离婚财产怎么分"},

    # ═══ 场景 D: 完全无关 ═══
    {"scenario_type": "完全无关", "specific_topic": "写诗", "user_input": "帮我写一首关于春天的诗"},
    {"scenario_type": "完全无关", "specific_topic": "天气查询", "user_input": "今天天气怎么样？适合出门吗"},
    {"scenario_type": "完全无关", "specific_topic": "股票推荐", "user_input": "最近买什么股票能赚钱？推荐几只"},
    {"scenario_type": "完全无关", "specific_topic": "情感咨询", "user_input": "我男朋友不理我了，我该怎么办"},
    {"scenario_type": "完全无关", "specific_topic": "医疗建议", "user_input": "我头痛三天了，吃什么药好"},
    {"scenario_type": "完全无关", "specific_topic": "菜谱查询", "user_input": "酸菜鱼怎么做？教我做一下"},
    {"scenario_type": "完全无关", "specific_topic": "旅游推荐", "user_input": "这个季节去哪里旅游最合适？推荐一下"},
    {"scenario_type": "完全无关", "specific_topic": "汽车推荐", "user_input": "预算 15 万买什么车好？推荐几款"},
    {"scenario_type": "完全无关", "specific_topic": "健身建议", "user_input": "怎么减肥最有效？推荐一个健身计划"},
    {"scenario_type": "完全无关", "specific_topic": "数学题", "user_input": "能帮我算一道高数题吗？求极限"},
    {"scenario_type": "完全无关", "specific_topic": "考试报名", "user_input": "教师资格证什么时候报名？流程是什么"},
    {"scenario_type": "完全无关", "specific_topic": "电影推荐", "user_input": "最近有什么好看的电影推荐吗"},
    {"scenario_type": "完全无关", "specific_topic": "租房建议", "user_input": "北京哪里租房性价比高？推荐几个小区"},
    {"scenario_type": "完全无关", "specific_topic": "宠物养护", "user_input": "猫咪总是抓沙发怎么办？有什么办法"},
    {"scenario_type": "完全无关", "specific_topic": "英语翻译", "user_input": "帮我把这段话翻译成英文"},
    {"scenario_type": "完全无关", "specific_topic": "手机推荐", "user_input": "推荐一款拍照好的手机"},
    {"scenario_type": "完全无关", "specific_topic": "求职简历", "user_input": "帮我写一份程序员求职简历"},
    {"scenario_type": "完全无关", "specific_topic": "经营建议", "user_input": "想在大学门口开奶茶店能赚钱吗"},
    {"scenario_type": "完全无关", "specific_topic": "音乐推荐", "user_input": "最近有什么好听的中文歌曲"},
    {"scenario_type": "完全无关", "specific_topic": "减肥食谱", "user_input": "能不能给我定制一周的减脂餐食谱"},
    {"scenario_type": "完全无关", "specific_topic": "签证办理", "user_input": "去日本旅游怎么办理签证"},
    {"scenario_type": "完全无关", "specific_topic": "修图技巧", "user_input": "怎么用手机修出好看的证件照"},
    {"scenario_type": "完全无关", "specific_topic": "编程问题", "user_input": "Python 怎么读取 Excel 文件"},
    {"scenario_type": "完全无关", "specific_topic": "星座运势", "user_input": "我今天狮子座的运势怎么样"},
    {"scenario_type": "完全无关", "specific_topic": "游戏攻略", "user_input": "LOL 怎么上分最快"},
]

PER_SCENARIO_RUNS = 1   # 每个场景只调一次，多样性来自不同 user_input

# ═══════════════════════════════════════════════════════════════
# 措辞多样性检查
# ═══════════════════════════════════════════════════════════════

def check_diversity(samples: list[dict], threshold: float = 0.9) -> list[tuple]:
    """TF-IDF + cosine similarity，返回相似度 > threshold 的对。"""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    answers = [s["answer"] for s in samples]
    if len(answers) < 2:
        return []

    vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 3))
    tfidf = vectorizer.fit_transform(answers)
    sim = cosine_similarity(tfidf)

    similar_pairs = []
    for i in range(len(answers)):
        for j in range(i + 1, len(answers)):
            if sim[i][j] > threshold:
                similar_pairs.append((samples[i]["id"], samples[j]["id"], sim[i][j]))
    return similar_pairs

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
                temperature=TEMPERATURE + random.uniform(0, 0.1),  # 微调温度增加措辞多样性
                max_tokens=GEN_MAX_TOKENS,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if answer and len(answer) >= 30:
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

def main():
    parser = argparse.ArgumentParser(description="阶段三 拒答样本生成")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--smoke", action="store_true", help="小样冒烟（10 条）")
    g.add_argument("--full", action="store_true", help="全量生成（~100 条）")
    args = parser.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    output_file = os.path.join(RAW_DIR, "card5_refusals.jsonl")
    progress_file = os.path.join(RAW_DIR, "card5_refusals_progress.json")

    smoke = args.smoke
    if smoke:
        random.seed(42)
        # 4 场景各取 2-3 个变体，共 10 个不同 user_input
        scenarios_a = [s for s in REFUSAL_SCENARIOS if s["scenario_type"] == "文书起草"]
        scenarios_b = [s for s in REFUSAL_SCENARIOS if s["scenario_type"] == "实时查询"]
        scenarios_c = [s for s in REFUSAL_SCENARIOS if s["scenario_type"] == "执业资质"]
        scenarios_d = [s for s in REFUSAL_SCENARIOS if s["scenario_type"] == "完全无关"]
        scenarios = (random.sample(scenarios_a, min(3, len(scenarios_a))) +
                     random.sample(scenarios_b, min(3, len(scenarios_b))) +
                     random.sample(scenarios_c, min(2, len(scenarios_c))) +
                     random.sample(scenarios_d, min(2, len(scenarios_d))))
        if os.path.exists(progress_file):
            os.remove(progress_file)
    else:
        scenarios = REFUSAL_SCENARIOS

    total_target = len(scenarios)
    print(f"阶段三 · 拒答生成 | 模式: {'冒烟' if smoke else '全量'} | 目标: {total_target} 条")
    print(f"  场景变体: {total_target}（每个不同 user_input 只调一次）")

    # 恢复进度
    done_combos = set()
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            done_combos = set(tuple(x) for x in json.load(f).get("done_combos", []))
        print(f"  恢复进度: 已完成 {len(done_combos)} 个组合")

    generated = []
    if os.path.exists(output_file):
        with open(output_file) as f:
            for line in f:
                if line.strip():
                    generated.append(json.loads(line))
        print(f"  已有输出: {len(generated)} 条")

    client = OpenAI(api_key=OPENKEY_API_KEY, base_url=OPENKEY_API_BASE)
    start_time = time.time()

    for scenario in scenarios:
        combo_key = (scenario["scenario_type"], scenario["user_input"])
        if combo_key in done_combos:
            continue

        user_prompt = PROMPT_D_USER.format(**scenario)
        answer = call_api(client, PROMPT_D_SYSTEM, user_prompt)

        if not answer:
            print(f"  生成失败: {scenario['specific_topic']}")
            answer = ""

        out = {
            "id": f"sft_card5_{len(generated) + 1:06d}",
            "card": 5,
            "scenario_type": 6,
            "source": "llm_generated_refusal",
            "generator_model": MODEL_NAME,
            "category": "",
            "dpo_targets": ["P6"],
            "refusal_subtype": scenario["scenario_type"],
            "question": scenario["user_input"],
            "answer": answer,
        }
        generated.append(out)
        done_combos.add(combo_key)

        # 每 5 条保存
        if len(generated) % 5 == 0:
            with open(output_file, "w") as f:
                for g in generated:
                    f.write(json.dumps(g, ensure_ascii=False) + "\n")
            with open(progress_file, "w") as f:
                json.dump({"done_combos": [list(c) for c in done_combos], "total": total_target}, f)

        elapsed = time.time() - start_time
        rate = len(generated) / elapsed if elapsed > 0 else 0
        print(f"  [{len(generated)}/{total_target}] {scenario['specific_topic']} "
              f"| {len(answer)}字 | 速率: {rate:.1f}条/s")

        time.sleep(SLEEP_BETWEEN * 0.5)

    # 最终统计
    lens = [len(g["answer"]) for g in generated if g["answer"]]
    failures = sum(1 for g in generated if not g["answer"])
    print(f"\n  完成: {len(generated)} 条 | 均长: {sum(lens)//len(lens) if lens else 0} 字 | 失败: {failures} 条")

    # 多样性检查
    if len(generated) >= 5:
        print("  措辞多样性检查...")
        try:
            similar = check_diversity(generated, threshold=0.9)
            if similar:
                print(f"    ⚠ {len(similar)} 对高度相似 (>0.9)，需人工改写")
                for a, b, score in similar[:5]:
                    print(f"      {a} ↔ {b}: {score:.3f}")
            else:
                print(f"    ✅ 无高度相似对")
        except ImportError:
            print("    (sklearn 未安装，跳过)")

    print(f"\n  输出: {output_file}")


if __name__ == "__main__":
    main()
