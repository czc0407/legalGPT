#!/usr/bin/env python3
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "config"))
sys.path.insert(0, SCRIPT_DIR)
"""
使用 LLM 对法律咨询数据进行 11 类自动分类。

分类体系来自 remap_taxonomy.py 定义的 11 个一级分类。
支持 DeepSeek / OpenAI 兼容 API，批量处理 + 断点续传。
"""

import json
import os
import time
from openai import OpenAI

# ══════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════

from llm_config import DEEPSEEK_API_KEY as API_KEY, DEEPSEEK_API_BASE as API_BASE, DEEPSEEK_MODEL as MODEL_NAME

INPUT_FILE = "data/sft/02_labeled/consultation_merged.jsonl"
OUTPUT_FILE = "data/sft/02_labeled/consultation_labeled.jsonl"
PROGRESS_FILE = "data/temp/classification_progress.json"

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)

BATCH_SIZE = 8           # 每批发送的问题数（含 reasoning 的模型需降低，预留 token 空间）
SLEEP_BETWEEN = 0.5      # 批次间等待秒数
MAX_RETRIES = 3
MAX_TOKENS = 3000        # 含 reasoning 的模型需要较大值，否则推理 token 吃满后输出为空

# ══════════════════════════════════════════════════════════════════
# 11 类分类体系（含决策指引）
# ══════════════════════════════════════════════════════════════════

TAXONOMY = {
    "婚姻家庭与继承": {
        "keys": "婚姻、离婚、抚养权、赡养、财产分割、同居、彩礼、家庭暴力、继承、遗嘱",
        "boundary": "离婚中的财产纠纷仍归此类，不归合同纠纷",
        "examples": "离婚需要什么手续？ / 父母去世后房产怎么继承？ / 孩子的抚养费标准是多少？",
    },
    "债权债务与金融": {
        "keys": "借钱、欠款、债务、贷款、抵押、担保、信用卡、保险理赔、票据、银行纠纷",
        "boundary": "民间借贷请归此类，合同性质借款也归此类",
        "examples": "朋友借钱不还没有欠条怎么办？ / 信用卡逾期会坐牢吗？ / 保险公司拒赔怎么办？",
    },
    "人身侵权与消费": {
        "keys": "人身伤害、医疗纠纷、消费维权、网络诈骗、教育培训、环境污染、名誉权、隐私权",
        "boundary": "非交通事故造成的伤害归此类；消费合同纠纷归此类而非合同纠纷",
        "examples": "在餐厅吃饭食物中毒怎么索赔？ / 被网络诈骗了怎么报警？ / 医院误诊怎么办？",
    },
    "劳动与工伤": {
        "keys": "工资、加班费、社保、裁员、开除、工伤、劳动合同、试用期、竞业限制",
        "boundary": "仅劳动者与用人单位关系；工伤归此类而非人身侵权",
        "examples": "公司不签劳动合同怎么办？ / 被公司无故开除能赔多少？ / 工伤认定需要什么材料？",
    },
    "综合法律服务": {
        "keys": "法律咨询、法律建议、律师委托、法律文书、综合、一般法律问题",
        "boundary": "问题涉及多个领域或无明显领域指向时归此类",
        "examples": "我需要请律师吗？ / 怎么写起诉状？ / 去法院立案需要什么材料？",
    },
    "合同与商业": {
        "keys": "合同违约、合同解除、合同效力、加盟、经销、招标、投标、国际贸易",
        "boundary": "商业合同纠纷归此类；劳动/消费合同归各自类；股权/公司事务归公司类",
        "examples": "签了合同对方不履行怎么办？ / 加盟被骗怎么维权？ / 合同违约金太高合理吗？",
    },
    "交通事故": {
        "keys": "车祸、交通事故、交强险、肇事逃逸、酒驾、车辆损伤、交通赔偿",
        "boundary": "涉及车辆的纠纷（含赔偿、保险）归此类，不归人身侵权",
        "examples": "被车撞了怎么索赔？ / 交通事故责任认定书几天出？ / 肇事逃逸怎么处理？",
    },
    "房产与土地": {
        "keys": "买房、卖房、租房、房产证、拆迁、征地、建设工程、土地使用权",
        "boundary": "房产买卖纠纷归此类而非合同纠纷；拆迁补偿归此类而非行政",
        "examples": "买的房子开发商延期交房怎么办？ / 拆迁补偿标准是多少？ / 租房押金不退怎么办？",
    },
    "刑事法律": {
        "keys": "犯罪、判刑、刑事案件、取保候审、自首、减刑、假释、拘役、逮捕",
        "boundary": "涉及刑事追诉/量刑的问题归此类；治安处罚等不涉刑的不归此类",
        "examples": "被刑事拘留了怎么办？ / 诈骗多少金额能立案？ / 取保候审需要什么条件？",
    },
    "行政与税务": {
        "keys": "行政复议、行政诉讼、税务、行政罚款、行政拘留、政府行政、签证、移民",
        "boundary": "对政府部门决定不服的归此类；涉及政府但不涉争议的（如拆迁）归房产而非行政",
        "examples": "对交警罚单不服怎么办？ / 个人所得税怎么申报？ / 行政复议申请书怎么写？",
    },
    "公司企业与知产": {
        "keys": "公司注册、股权、股东、法人、上市、破产、商标、专利、著作权、商业秘密",
        "boundary": "公司内部治理/股东纠纷归此类；劳动纠纷归劳动类",
        "examples": "股东不按约定出资怎么办？ / 公司破产清算的流程是什么？ / 商标被侵权怎么维权？",
    },
}


def build_prompt(questions):
    """构建分类 prompt，传入一批问题"""
    # 类别描述
    taxonomy_desc = ""
    for name, info in TAXONOMY.items():
        taxonomy_desc += (
            f"- **{name}**\n"
            f"  关键词：{info['keys']}\n"
            f"  边界规则：{info['boundary']}\n"
        )

    questions_text = ""
    for i, q in enumerate(questions):
        questions_text += f"{i}. {q}\n"

    prompt = f"""你是一位法律数据标注专家。请对以下法律咨询问题进行分类。

## 分类体系（11 类）

{taxonomy_desc}

## 分类原则
1. 以问题的**核心法律诉求**判断，而非表面关键词
2. 如果一个问题涉及多个领域，选择最核心的领域
3. 如果无法明确归类，选择"综合法律服务"
4. 劳动工伤问题（工资、裁员、社保、工伤）归"劳动与工伤"
5. 借款/欠款/债务问题归"债权债务与金融"
6. 仅涉及车祸/交通肇事的问题归"交通事故"
7. 涉及犯罪/判刑/拘留的问题归"刑事法律"

## 待分类问题
{questions_text}

## 输出格式
严格输出一个 JSON 数组，每个元素只包含 "label" 字段，按问题顺序排列。
不要输出任何其他内容。

示例输出：
```json
[{{"label": "刑事法律"}}, {{"label": "婚姻家庭与继承"}}, {{"label": "劳动与工伤"}}]
```

现在请输出上述 {len(questions)} 个问题的分类结果："""

    return prompt


def parse_response(response_text):
    """解析 LLM 返回的分类结果，容忍截断"""
    # 处理空响应
    if not response_text or not response_text.strip():
        return None

    try:
        text = response_text.strip()
        # 如果被 markdown 代码块包裹，去掉
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉首行 ```json 和末行 ```
            if len(lines) > 2:
                text = "\n".join(lines[1:-1]).strip()
            else:
                text = lines[-1] if len(lines) == 1 else lines[1]

        # 尝试解析完整 JSON
        results = json.loads(text)
        labels = [item["label"] for item in results]
    except json.JSONDecodeError as e:
        # JSON 截断：尝试逐个提取已完整的标签
        print(f"  JSON 截断 ({e})，尝试恢复部分标签...")
        labels = _recover_truncated_labels(text)
        if not labels:
            return None

    # 验证标签
    valid = set(TAXONOMY.keys())
    for label in labels:
        if label not in valid:
            print(f"  无效标签 '{label}'，回退")
            return None

    return labels


def _recover_truncated_labels(text):
    """从截断的 JSON 数组中提取已完整的标签对象"""
    import re
    matches = re.findall(r'\{"label":\s*"([^"]+)"\}', text)
    return matches if matches else None


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    # 加载数据
    with open(INPUT_FILE, "r") as f:
        all_data = [json.loads(line) for line in f if line.strip()]
    print(f"加载 {len(all_data)} 条待分类数据")

    # 加载进度
    done_ids = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            progress = json.load(f)
            done_ids = set(progress.get("done_ids", []))
        print(f"恢复进度: 已完成 {len(done_ids)} 条")

    # 加载已有输出
    labeled = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    labeled.append(item)
                    done_ids.add(item["id"])
        print(f"已有输出: {len(labeled)} 条")

    # 筛选待处理
    pending = [d for d in all_data if d["id"] not in done_ids]
    print(f"待处理: {len(pending)} 条")
    if not pending:
        print("全部完成！")
        return

    # 初始化 API 客户端
    client = OpenAI(api_key=API_KEY, base_url=API_BASE)

    # 批量处理
    total = len(pending)
    processed = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch = pending[batch_start:batch_end]

        questions = [d["query"] for d in batch]
        prompt = build_prompt(questions)

        # 重试
        labels = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "你是一个法律文书分类专家，输出严格JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=MAX_TOKENS,
                )
                response_text = response.choices[0].message.content or ""
                if not response_text.strip():
                    raise ValueError("API 返回空内容（可能 reasoning token 耗尽 max_tokens）")
                labels = parse_response(response_text)
                if labels is not None:
                    break
            except Exception as e:
                print(f"  API 调用失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(3 * (attempt + 1))

        if labels is None:
            # 如果全部重试失败，标记为"综合法律服务"
            labels = ["综合法律服务"] * len(questions)
            print(f"  批次 {batch_start}-{batch_end} 分类失败，标记为默认值")

        # 确保标签数量匹配
        if len(labels) != len(questions):
            print(f"  标签数量不匹配: {len(labels)} vs {len(questions)}，补全为默认值")
            labels = labels[: len(questions)] + ["综合法律服务"] * (
                len(questions) - len(labels)
            )

        # 写入结果
        for d, label in zip(batch, labels):
            d["label"] = label
            labeled.append(d)
            done_ids.add(d["id"])

        processed += len(batch)

        # 每批次后保存
        with open(OUTPUT_FILE, "w") as f:
            for item in labeled:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"done_ids": list(done_ids), "total": len(all_data)}, f)

        print(f"  进度: {processed}/{total} ({processed * 100 // total}%) | batch={len(batch)}")

        if processed < total:
            time.sleep(SLEEP_BETWEEN)

    # 最终统计
    from collections import Counter

    label_counts = Counter(d.get("label", "未知") for d in labeled)
    print(f"\n{'=' * 50}")
    print(f"  分类完成！共 {len(labeled)} 条")
    print(f"  标签分布：")
    for label, count in label_counts.most_common():
        pct = count / len(labeled) * 100
        print(f"    {label:<16s}  {count:>5} ({pct:>5.1f}%)")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
