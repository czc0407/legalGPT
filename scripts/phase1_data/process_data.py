#!/usr/bin/env python3
"""
处理法律咨询 SFT 数据的清洗脚本。

处理流程：
  1. DISC-Law-SFT-Pair-QA-released.jsonl
      - 提取法律知识问答 (id 0-15986)     -> DISC_knowledge_qa.jsonl
      - 提取咨询类问题 (id 55808-66421)   -> DISC_consultation_clean.jsonl
        清洗规则：
          a) 删除拒绝回答（无法理解/无法提供/AI免责）
          b) 为无《》引用的回答标记 citation_quality=low
          c) 删除 response 中的具体条文编号（第X条）
  2. zixun_gpt4.json
      - 删除含"参考法条"的条目
      - 删除 response 中的具体条文编号（第X条）
      - 仅保留 query 和 response 字段     -> zixun_gpt4_clean.jsonl
  3. 合并两个咨询数据源                      -> consultation_merged.jsonl
"""

import json
import re
import os

# ─── 路径配置 ───────────────────────────────────────────────────────
RAW_DIR = 'data/external'
OUT_DIR = 'data/processed'
RAW_PROCESSED_DIR = os.path.join(OUT_DIR, 'raw_processed')   # 清洗后产物
LABELED_DIR = os.path.join(OUT_DIR, 'labeled')               # 合并 + 标注产物

DISC_PATH = os.path.join(RAW_DIR, 'DISC-Law-SFT-Pair-QA-released.jsonl')
ZIXUN_PATH = os.path.join(RAW_DIR, 'zixun_gpt4.json')

os.makedirs(RAW_PROCESSED_DIR, exist_ok=True)
os.makedirs(LABELED_DIR, exist_ok=True)

# ─── 条文编号清洗函数 ──────────────────────────────────────────────────


def clean_article_numbers(text):
    """
    删除具体条文编号，保留法条名称引用。
    例如:
      "根据《民法典》第一千零七十九条的规定" -> "根据《民法典》的规定"
      "根据《刑法》第266条规定"             -> "根据《刑法》规定"
      "依据《民法典》第1079条、第1080条"    -> "依据《民法典》"
    """
    # 模式1: 《XXX》第N条+的规定/之规定/款规定
    text = re.sub(
        r'(《[^》]+》)'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:[、，,]?\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:第[零一二三四五六七八九十百千\d]+款)?'
        r'(?:[之的]?规定)?',
        r'\1的规定',
        text,
    )
    # 模式2: 孤立条文引用（不在《》后的第X条）
    text = re.sub(
        r'(?:以及|及|和|与|或|如|参考|诸如|例如|涉及|包括|即|见|'
        r'根据|依据|按照|参照|并且根据|而依据|'
        r'特别是|尤其是|其中|'
        r'，|,|、)\s*'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:\s*[、，,]\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:[的之]规定)?',
        '',
        text,
    )
    # 模式2b: 括号中的条文: （第X条）
    text = re.sub(
        r'[（(]\s*第[零一二三四五六七八九十百千\d]+条\s*[）)]',
        '',
        text,
    )
    # 模式3: 孤立 "第X条" 出现在句首或作为列举项
    text = re.sub(
        r'[。.；;]\s*'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:\s*[、，,]\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:[的之]规定)?',
        r'。',
        text,
    )
    # 清理多余空白和标点
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'，{2,}', '，', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'、{2,}', '', text)
    # 修复 "根据  的规定" 多余空格, 以及 "根据的规定"
    text = re.sub(r'根据\s+的规定', '根据规定', text)
    # 兜底修复: 替换导致的 "规定规定" → "规定"
    text = text.replace('的规定规定', '的规定')
    text = text.replace('规定规定', '规定')
    text = text.replace('之规定之规定', '之规定')
    return text.strip()


# ====================================================================
#  1. 处理 DISC-Law-SFT  数据
# ====================================================================
print("=" * 80)
print("  1. 处理 DISC-Law-SFT 数据")
print("=" * 80)

with open(DISC_PATH, 'r') as f:
    disc_lines = f.readlines()
print(f"  总行数: {len(disc_lines)}")

# ─── 拒绝回答的匹配模式 ────────────────────────────────────────────
# 这些才是真正的"无法回答"，不包括"法律上不存在"之类的有效否定答复
REJECTION_PATTERNS = [
    r'很抱歉，.{0,20}无法理解您的问题',
    r'抱歉，.{0,5}作为.{0,10}人工智能.{0,10}(?:无法|不能)',
    r'我无法提供您具体案件的信息',
    r'我无法(?:回答|处理|解决).{0,20}问题',
    r'(?:非常)?抱歉.{0,10}我.{0,10}(?:无法|不能).{0,20}(?:回答|帮助|处理)',
    r'请您提供更多的背景信息',
]


def is_rejection(text):
    """判断回答是否为拒绝回答"""
    for pattern in REJECTION_PATTERNS:
        if re.search(pattern, text):
            return True
    # 短回复 + 拒绝关键词组合
    if len(text) < 80:
        short_reject_keywords = ['无法理解', '无法回答', '无法帮助']
        if any(kw in text for kw in short_reject_keywords):
            return True
    return False


# ─── 法律名称白名单 ─────────────────────────────────────────────────
# 仅收录现行有效的法律/法规/条例。已废止的单行法（婚姻法、合同法、继承法、
# 担保法、物权法、侵权责任法等）不在此列——它们已被民法典各分编取代。
# 生成和重写数据时仅使用此列表中的名称，避免训练数据中出现过时引用。
SPECIFIC_LAW_NAMES = [
    # 基本法
    '民法典', '刑法', '宪法',
    # 劳动与社会保障
    '劳动法', '劳动合同法', '社会保险法', '工伤保险条例',
    '劳动争议调解仲裁法',
    # 经济与商法
    '公司法', '合伙企业法', '个人独资企业法', '企业破产法',
    '证券法', '保险法', '票据法', '信托法',
    '反不正当竞争法', '反垄断法', '电子商务法',
    '消费者权益保护法', '产品质量法', '食品安全法',
    # 知识产权
    '专利法', '商标法', '著作权法',
    # 行政法与程序法
    '行政处罚法', '行政许可法', '行政强制法',
    '行政复议法', '行政诉讼法',
    '刑事诉讼法', '民事诉讼法', '仲裁法',
    # 专门法
    '治安管理处罚法', '道路交通安全法', '网络安全法',
    '数据安全法', '个人信息保护法',
    '未成年人保护法', '妇女权益保障法', '老年人权益保障法',
    '反家庭暴力法', '法律援助法',
    # 房产与土地
    '土地管理法', '城市房地产管理法', '农村土地承包法',
    # 环境与资源
    '环境保护法', '环境影响评价法',
    # 税收
    '税收征收管理法', '个人所得税法', '企业所得税法',
    # 其他
    '建筑法', '招标投标法', '海商法', '海事诉讼特别程序法',
    '国防法', '国家安全法',
]


def contains_specific_law_reference(text):
    """
    检查 response 中 根据/依据 后是否引用具体法律实体名称。
    区别于模糊表述如"根据中国法律""根据您的描述"。
    """
    for m in re.finditer(r'(根据|依据)', text):
        pos = m.end()
        window = text[pos:pos + 20]  # 取后20字
        window = re.split(r'[，,。.；;、\s]', window)[0]  # 截到标点
        window = window.strip()
        if not window:
            continue

        # ── 排除模糊/无实体的表述 ──
        # 1. 纯通用词
        if window in ('法律', '法律法规', '法', '规定', '条例', '相关规定', '法律规定'):
            continue
        # 2. 模糊前缀
        vague_prefixes = (
            '中国法律', '中国的法律', '中国法律规定', '中国的法律规定',
            '中国相关法律', '中国的相关法律', '中国相关法律法规',
            '中国有关法律', '中国现行法律',
            '相关法律', '有关法律', '上述法律', '该法律', '此法', '彼法',
            '相关规定', '有关规定', '上述规定', '该规定',
            '相关条例', '有关条例',
            '相关法规', '有关法规',
            '您', '你', '我', '我的', '我们',
            '提供', '描述', '问题', '情况', '所',
            '具体', '实际', '自身', '案件',
            '法律层面', '法律角度',
            '我对', '一般', '通常', '一般情况',
        )
        if window.startswith(vague_prefixes):
            continue

        # ── 命中具体法律实体 ──
        if any(law in window for law in SPECIFIC_LAW_NAMES):
            return True

    return False


def classify_citation(text):
    """
    三档分类:
      high   - 含《》书名号引用
      medium - 无《》但含 根据/依据 + 具体法律实体
      low    - 其余
    """
    if '《' in text:
        return 'high'
    if contains_specific_law_reference(text):
        return 'medium'
    return 'low'


# ─── 1a. 提取法律知识问答 (0-15986) ───────────────────────────────
print("\n  --- 1a. 提取法律知识问答 (id 0-15986) ---")

knowledge_qa = []
qa_article_cleaned = 0
for i in range(0, 15987):  # inclusive
    obj = json.loads(disc_lines[i])
    cleaned_response = clean_article_numbers(obj['output'])
    if cleaned_response != obj['output']:
        qa_article_cleaned += 1
    knowledge_qa.append({
        'id': f"disc_qa_{len(knowledge_qa) + 1:06d}",
        'source': 'DISC-Law-SFT',
        'type': 'knowledge_qa',
        'query': obj['input'],
        'response': cleaned_response,
    })

print(f"  提取: {len(knowledge_qa)} 条")
print(f"  条文编号清洗: {qa_article_cleaned} (已删除第X条)")

# ─── 1b. 提取并清洗咨询类问题 (55808-66421) ────────────────────────
print("\n  --- 1b. 提取并清洗咨询类问题 (id 55808-66421) ---")

disc_consultation = []
stats = {
    'total_extracted': 0,
    'rejection_removed': 0,
    'citation_high': 0,
    'citation_medium': 0,
    'citation_low': 0,
    'article_cleaned': 0,
    'kept': 0,
}

rejection_examples = []
medium_examples = []
no_citation_examples = []

for i in range(55808, 66422):  # inclusive
    obj = json.loads(disc_lines[i])
    stats['total_extracted'] += 1
    output = obj['output']

    # 清洗 a: 拒绝回答
    if is_rejection(output):
        stats['rejection_removed'] += 1
        if len(rejection_examples) < 5:
            rejection_examples.append({
                'original_id': obj['id'],
                'query': obj['input'][:80],
                'output_preview': output[:120],
            })
        continue

    # 清洗 b: 引用质量三档分类
    citation_quality = classify_citation(output)
    stats[f'citation_{citation_quality}'] += 1
    if citation_quality == 'low' and len(no_citation_examples) < 5:
        no_citation_examples.append({
            'original_id': obj['id'],
            'query': obj['input'][:80],
            'output_preview': output[:120],
        })
    if citation_quality == 'medium' and len(medium_examples) < 3:
        medium_examples.append({
            'original_id': obj['id'],
            'query': obj['input'][:80],
            'output_preview': output[:120],
        })

    # 清洗 c: 删除条文编号
    cleaned_output = clean_article_numbers(output)
    if cleaned_output != output:
        stats['article_cleaned'] += 1

    disc_consultation.append({
        'id': f"disc_consult_{stats['kept'] + 1:06d}",
        'source': 'DISC-Law-SFT',
        'type': 'consultation',
        'query': obj['input'],
        'response': cleaned_output,
        'citation_quality': citation_quality,
    })
    stats['kept'] += 1

print(f"  提取总数:        {stats['total_extracted']}")
print(f"  拒绝回答:        {stats['rejection_removed']} (已删除)")
print(f"  引用质量-high:   {stats['citation_high']} (含《》法条引用)")
print(f"  引用质量-medium: {stats['citation_medium']} (无《》但有'根据/依据')")
print(f"  引用质量-low:    {stats['citation_low']} (既无《》也无'根据/依据'，待删除)")
print(f"  条文编号清洗:    {stats['article_cleaned']} (已删除第X条)")
print(f"  最终保留:        {stats['kept']}")

# 打印示例
if rejection_examples:
    print(f"\n  --- 拒绝回答示例 ---")
    for ex in rejection_examples:
        print(f"  [{ex['original_id']}] {ex['query']}")
        print(f"    -> {ex['output_preview']}...")
        print()

if medium_examples:
    print(f"  --- medium 示例 (无《》但有'根据/依据') ---")
    for ex in medium_examples:
        print(f"  [{ex['original_id']}] {ex['query']}")
        print(f"    -> {ex['output_preview']}...")
        print()

if no_citation_examples:
    print(f"  --- low 示例 (既无《》也无'根据/依据') ---")
    for ex in no_citation_examples:
        print(f"  [{ex['original_id']}] {ex['query']}")
        print(f"    -> {ex['output_preview']}...")
        print()


# ====================================================================
#  2. 处理 zixun_gpt4 数据
# ====================================================================
print("=" * 80)
print("  2. 处理 zixun_gpt4 数据")
print("=" * 80)

with open(ZIXUN_PATH, 'r') as f:
    zx_data = json.load(f)

print(f"  总条目数: {len(zx_data)}")

# ─── 清洗函数 ───────────────────────────────────────────────────────


def clean_article_numbers(text):
    """
    删除具体条文编号，保留法条名称引用。
    例如:
      "根据《民法典》第一千零七十九条的规定" -> "根据《民法典》的规定"
      "根据《刑法》第266条规定"             -> "根据《刑法》规定"
      "依据《民法典》第1079条、第1080条"    -> "依据《民法典》"
    """
    # 模式1: 《XXX》第N条+的规定/之规定/款规定
    # 匹配 "的规定" 和 "之规定"，避免替换后重复
    text = re.sub(
        r'(《[^》]+》)'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:[、，,]?\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:第[零一二三四五六七八九十百千\d]+款)?'
        r'(?:[之的]?规定)?',
        r'\1的规定',
        text,
    )
    # 模式2: 孤立条文引用（不在《》后的第X条）
    # 包括: 连接词+第X条、介词+第X条、括号中的第X条
    text = re.sub(
        r'(?:以及|及|和|与|或|如|参考|诸如|例如|涉及|包括|即|见|'
        r'根据|依据|按照|参照|并且根据|而依据|'
        r'特别是|尤其是|其中|'
        r'，|,|、)\s*'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:\s*[、，,]\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:[的之]规定)?',
        '',
        text,
    )
    # 模式2b: 括号中的条文: （第X条）
    text = re.sub(
        r'[（(]\s*第[零一二三四五六七八九十百千\d]+条\s*[）)]',
        '',
        text,
    )
    # 模式3: 孤立 "第X条" 出现在句首或作为列举项
    text = re.sub(
        r'[。.；;]\s*'
        r'第[零一二三四五六七八九十百千\d]+条'
        r'(?:\s*[、，,]\s*第[零一二三四五六七八九十百千\d]+条)*'
        r'(?:[的之]规定)?',
        r'。',
        text,
    )
    # 清理多余空白和标点
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'，{2,}', '，', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'、{2,}', '', text)
    # 修复 "根据  的规定" 多余空格, 以及 "根据的规定"
    text = re.sub(r'根据\s+的规定', '根据规定', text)
    # 兜底修复: 替换导致的 "规定规定" → "规定"
    text = text.replace('的规定规定', '的规定')
    text = text.replace('规定规定', '规定')
    text = text.replace('之规定之规定', '之规定')
    return text.strip()


zixun_clean = []
zx_stats = {
    'total': len(zx_data),
    'ref_removed': 0,
    'article_cleaned': 0,
    'kept': 0,
}

ref_examples = []
article_examples = []

for item in zx_data:
    query = item['query']
    raw_response = item['response']

    # 清洗 a: 删除含"参考法条"的条目
    if '参考法条' in raw_response:
        zx_stats['ref_removed'] += 1
        if len(ref_examples) < 3:
            idx = raw_response.find('参考法条')
            ref_examples.append({
                'query': query[:60],
                'context': raw_response[max(0, idx - 40):idx + 80],
            })
        continue

    # 清洗 b: 删除具体条文编号
    cleaned = clean_article_numbers(raw_response)
    if cleaned != raw_response:
        zx_stats['article_cleaned'] += 1
        if len(article_examples) < 3:
            article_examples.append({
                'query': query[:60],
                'before': re.findall(r'第[零一二三四五六七八九十百千\d]+条', raw_response)[:3],
                'after_preview': cleaned[:150],
            })

    zixun_clean.append({
        'id': f"zx_consult_{zx_stats['kept'] + 1:06d}",
        'source': 'zixun_gpt4',
        'type': 'consultation',
        'query': query,
        'response': cleaned,
    })
    zx_stats['kept'] += 1

print(f"  总条目数:       {zx_stats['total']}")
print(f"  参考法条删除:   {zx_stats['ref_removed']} (含'参考法条')")
print(f"  条文编号清洗:   {zx_stats['article_cleaned']} (已删除第X条)")
print(f"  最终保留:       {zx_stats['kept']}")

if ref_examples:
    print(f"\n  --- 参考法条删除示例 ---")
    for ex in ref_examples:
        print(f"  Query: {ex['query']}...")
        print(f"  匹配内容: ...{ex['context']}...")
        print()

if article_examples:
    print(f"  --- 条文编号清洗示例 ---")
    for ex in article_examples:
        print(f"  Query: {ex['query']}...")
        print(f"  被删除的条文: {ex['before']}")
        print(f"  清洗后: {ex['after_preview']}...")
        print()


# ====================================================================
#  3. 写入输出文件
# ====================================================================
print("=" * 80)
print("  3. 写入输出文件")
print("=" * 80)


def write_jsonl(path, data):
    with open(path, 'w') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"  写入: {path} ({len(data)} 条)")


# 文件 1: 法律知识问答
out1 = os.path.join(RAW_PROCESSED_DIR, 'DISC_knowledge_qa.jsonl')
write_jsonl(out1, knowledge_qa)

# 文件 2: 清洗后的 DISC 咨询类问题
out2 = os.path.join(RAW_PROCESSED_DIR, 'DISC_consultation_clean.jsonl')
write_jsonl(out2, disc_consultation)

# 文件 3: 清洗后的 zixun_gpt4
out3 = os.path.join(RAW_PROCESSED_DIR, 'zixun_gpt4_clean.jsonl')
write_jsonl(out3, zixun_clean)

# 文件 4: 合并两个数据源的咨询类问题
all_consultation = []
for i, item in enumerate(disc_consultation):
    all_consultation.append({
        'id': f"consult_{len(all_consultation) + 1:06d}",
        'source': item['source'],
        'type': 'consultation',
        'query': item['query'],
        'response': item['response'],
        'citation_quality': item.get('citation_quality'),
        'original_id': item['id'],
    })
for item in zixun_clean:
    all_consultation.append({
        'id': f"consult_{len(all_consultation) + 1:06d}",
        'source': item['source'],
        'type': 'consultation',
        'query': item['query'],
        'response': item['response'],
        'original_id': item['id'],
    })

out4 = os.path.join(LABELED_DIR, 'consultation_merged.jsonl')
write_jsonl(out4, all_consultation)


# ====================================================================
#  4. 统计汇总
# ====================================================================
print("\n" + "=" * 80)
print("  处理完成 -- 统计汇总")
print("=" * 80)

print(f"""
  文件                                       条数        说明
  ─────────────────────────────────────────────────────────────────
  DISC_knowledge_qa.jsonl              {len(knowledge_qa):>8}   法律知识问答 (id 0-15986)
    - 其中条文编号清洗                {qa_article_cleaned:>8}   已删除第X条
  DISC_consultation_clean.jsonl        {len(disc_consultation):>8}   咨询类问题 (清洗后)
    - 其中 citation_quality=high      {stats['citation_high']:>8}   含《》法条
    - 其中 citation_quality=medium    {stats['citation_medium']:>8}   无《》但有'根据/依据'
    - 其中 citation_quality=low       {stats['citation_low']:>8}   既无《》也无'根据/依据'(待删)
    - 其中条文编号清洗                {stats['article_cleaned']:>8}   已删除第X条
  zixun_gpt4_clean.jsonl               {len(zixun_clean):>8}   咨询类回复 (清洗后)
  consultation_merged.jsonl            {len(all_consultation):>8}   两源合并的咨询数据
  ─────────────────────────────────────────────────────────────────
  咨询数据总计                          {len(all_consultation):>8}
  法律知识问答                          {len(knowledge_qa):>8}
""")

# 验证
assert len(knowledge_qa) == 15987, f"Knowledge QA count mismatch: {len(knowledge_qa)}"
assert len(disc_consultation) + stats['rejection_removed'] == stats['total_extracted']
assert len(all_consultation) == len(disc_consultation) + len(zixun_clean)
assert len(zixun_clean) + zx_stats['ref_removed'] == zx_stats['total']

print("  所有数据一致性校验通过。")
