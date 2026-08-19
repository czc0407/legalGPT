#!/usr/bin/env python3
"""
80 个原始华律网标签 → 11 类法律咨询分类体系的映射字典。

用法：
    from taxonomy_config import LABEL_REMAP

直接运行 (python taxonomy_config.py) 打印分析报告。
"""

import json
from collections import Counter, defaultdict

# ─── Remapping dictionary ───────────────────────────────────────────
# Each original label maps to (一级分类_CN, 一级分类_EN, optional_二级分类)
LABEL_REMAP = {
    # ================================================
    # 1. 婚姻家庭与继承  Marriage, Family & Inheritance
    # ================================================
    '婚姻家庭':   ('婚姻家庭与继承', 'Marriage, Family & Inheritance', '婚姻家庭'),
    '离婚':       ('婚姻家庭与继承', 'Marriage, Family & Inheritance', '离婚'),
    '继承':       ('婚姻家庭与继承', 'Marriage, Family & Inheritance', '继承'),

    # ================================================
    # 2. 债权债务与金融  Debt, Credit & Finance
    # ================================================
    '债权债务':   ('债权债务与金融', 'Debt, Credit & Finance', '债权债务'),
    '抵押担保':   ('债权债务与金融', 'Debt, Credit & Finance', '抵押担保'),
    '银行':       ('债权债务与金融', 'Debt, Credit & Finance', '银行'),
    '票据':       ('债权债务与金融', 'Debt, Credit & Finance', '票据'),
    '邮政储蓄':   ('债权债务与金融', 'Debt, Credit & Finance', '邮政储蓄'),
    '融资借款':   ('债权债务与金融', 'Debt, Credit & Finance', '融资借款'),
    '金融证券':   ('债权债务与金融', 'Debt, Credit & Finance', '金融证券'),
    '期货交易':   ('债权债务与金融', 'Debt, Credit & Finance', '期货交易'),
    '保险理赔':   ('债权债务与金融', 'Debt, Credit & Finance', '保险理赔'),
    '资产拍卖':   ('债权债务与金融', 'Debt, Credit & Finance', '资产拍卖'),
    '经济仲裁':   ('债权债务与金融', 'Debt, Credit & Finance', '经济仲裁'),

    # ================================================
    # 3. 劳动与工伤  Labor & Work Injury
    # ================================================
    '劳动纠纷':   ('劳动与工伤', 'Labor & Work Injury', '劳动纠纷'),
    '工伤赔偿':   ('劳动与工伤', 'Labor & Work Injury', '工伤赔偿'),

    # ================================================
    # 4. 交通事故  Traffic Accidents
    # ================================================
    '交通事故':   ('交通事故', 'Traffic Accidents', None),

    # ================================================
    # 5. 合同与商业  Contracts & Commerce
    # ================================================
    '合同纠纷':   ('合同与商业', 'Contracts & Commerce', '合同纠纷'),
    '合同审查':   ('合同与商业', 'Contracts & Commerce', '合同审查'),
    '经销代理':   ('合同与商业', 'Contracts & Commerce', '经销代理'),
    '加盟维权':   ('合同与商业', 'Contracts & Commerce', '加盟维权'),
    '合伙联营':   ('合同与商业', 'Contracts & Commerce', '合伙联营'),
    '招商引资':   ('合同与商业', 'Contracts & Commerce', '招商引资'),
    '招标投标':   ('合同与商业', 'Contracts & Commerce', '招标投标'),
    '倾销补贴':   ('合同与商业', 'Contracts & Commerce', '倾销补贴'),
    '国际贸易':   ('合同与商业', 'Contracts & Commerce', '国际贸易'),
    '合资合作':   ('合同与商业', 'Contracts & Commerce', '合资合作'),
    '兼并收购':   ('合同与商业', 'Contracts & Commerce', '兼并收购'),
    '改制重组':   ('合同与商业', 'Contracts & Commerce', '改制重组'),
    '海事海商':   ('合同与商业', 'Contracts & Commerce', '海事海商'),
    '涉外仲裁':   ('合同与商业', 'Contracts & Commerce', '涉外仲裁'),

    # ================================================
    # 6. 人身侵权与消费  Personal Injury, Torts & Consumer Rights
    # ================================================
    '人身损害':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '人身损害'),
    '侵权':       ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '侵权'),
    '医疗纠纷':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '医疗纠纷'),
    '消费权益':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '消费权益'),
    '广告宣传':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '广告宣传'),
    '电信通讯':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '电信通讯'),
    '网络法律':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '网络法律'),
    '环境污染':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '环境污染'),
    '污染损害':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '污染损害'),
    '旅游':       ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '旅游'),
    '求学教育':   ('人身侵权与消费', 'Personal Injury, Torts & Consumer Rights', '求学教育'),

    # ================================================
    # 7. 房产与土地  Real Estate, Land & Construction
    # ================================================
    '房产纠纷':   ('房产与土地', 'Real Estate, Land & Construction', '房产纠纷'),
    '拆迁安置':   ('房产与土地', 'Real Estate, Land & Construction', '拆迁安置'),
    '建设工程':   ('房产与土地', 'Real Estate, Land & Construction', '建设工程'),
    '土地纠纷':   ('房产与土地', 'Real Estate, Land & Construction', '土地纠纷'),

    # ================================================
    # 8. 刑事法律  Criminal Law
    # ================================================
    '刑事辩护':   ('刑事法律', 'Criminal Law', '刑事辩护'),
    '取保候审':   ('刑事法律', 'Criminal Law', '取保候审'),
    '毒品犯罪':   ('刑事法律', 'Criminal Law', '毒品犯罪'),
    '刑事自诉':   ('刑事法律', 'Criminal Law', '刑事自诉'),
    '经济犯罪':   ('刑事法律', 'Criminal Law', '经济犯罪'),
    '暴力犯罪':   ('刑事法律', 'Criminal Law', '暴力犯罪'),
    '死刑辩护':   ('刑事法律', 'Criminal Law', '死刑辩护'),
    '公安国安':   ('刑事法律', 'Criminal Law', '公安国安'),

    # ================================================
    # 9. 公司企业与知识产权  Corporate & Intellectual Property
    # ================================================
    '公司法':     ('公司企业与知产', 'Corporate & Intellectual Property', '公司法'),
    '破产清算':   ('公司企业与知产', 'Corporate & Intellectual Property', '破产清算'),
    '公司解散':   ('公司企业与知产', 'Corporate & Intellectual Property', '公司解散'),
    '个人独资':   ('公司企业与知产', 'Corporate & Intellectual Property', '个人独资'),
    '公司上市':   ('公司企业与知产', 'Corporate & Intellectual Property', '公司上市'),
    '新三板':     ('公司企业与知产', 'Corporate & Intellectual Property', '新三板'),
    '股权纠纷':   ('公司企业与知产', 'Corporate & Intellectual Property', '股权纠纷'),
    '股权激励':   ('公司企业与知产', 'Corporate & Intellectual Property', '股权激励'),
    '外商投资':   ('公司企业与知产', 'Corporate & Intellectual Property', '外商投资'),
    '知识产权':   ('公司企业与知产', 'Corporate & Intellectual Property', '知识产权'),
    '著作权':     ('公司企业与知产', 'Corporate & Intellectual Property', '著作权'),
    '专利':       ('公司企业与知产', 'Corporate & Intellectual Property', '专利'),
    '反不正当竞争':('公司企业与知产', 'Corporate & Intellectual Property', '反不正当竞争'),
    '矿产资源':   ('公司企业与知产', 'Corporate & Intellectual Property', '矿产资源'),
    '水利电力':   ('公司企业与知产', 'Corporate & Intellectual Property', '水利电力'),

    # ================================================
    # 10. 行政与税务  Administrative & Tax
    # ================================================
    '行政复议':   ('行政与税务', 'Administrative & Tax', '行政复议'),
    '行政诉讼':   ('行政与税务', 'Administrative & Tax', '行政诉讼'),
    '行政':       ('行政与税务', 'Administrative & Tax', '行政综合'),
    '税务':       ('行政与税务', 'Administrative & Tax', '税务'),
    '海关商检':   ('行政与税务', 'Administrative & Tax', '海关商检'),
    '移民留学':   ('行政与税务', 'Administrative & Tax', '移民留学'),

    # ================================================
    # 11. 综合法律服务  General Legal Services
    # ================================================
    '综合咨询':   ('综合法律服务', 'General Legal Services', '综合咨询'),
    '法律顾问':   ('综合法律服务', 'General Legal Services', '法律顾问'),
    '法律文书代写':('综合法律服务', 'General Legal Services', '法律文书代写'),
    '调解谈判':   ('综合法律服务', 'General Legal Services', '调解谈判'),
    '工商查询':   ('综合法律服务', 'General Legal Services', '工商查询'),
}


# ══════════════════════════════════════════════════════════════════════
# 直接运行时打印分析报告
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import os
    CLEAN_PATH = '/Users/chenzichan/Intern/legalGPT/data/sft/01_cleaned/hualv_question_clean.jsonl'
    RAW_PATH = '/Users/chenzichan/Intern/legalGPT/data/external/question_2.json'
    DATA_PATH = CLEAN_PATH if os.path.exists(CLEAN_PATH) else RAW_PATH
    print(f"  数据源: {DATA_PATH}")

    titles = []
    with open(DATA_PATH, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                titles.append(json.loads(line).get('title', ''))

    total = len(titles)
    orig_counter = Counter(titles)

    # ─── Remap ──────────────────────────────────────────────────────
    level1_counter = Counter()
    level2_detail = defaultdict(Counter)

    unmapped = []
    for title, count in orig_counter.items():
        clean_title = title.strip('[]')
        if clean_title in LABEL_REMAP:
            l1_cn, l1_en, l2 = LABEL_REMAP[clean_title]
            level1_counter[l1_cn] += count
            if l2:
                level2_detail[l1_cn][l2] += count
        else:
            unmapped.append(title)

    # ─── Print report ───────────────────────────────────────────────
    print("=" * 100)
    print("  LEGAL CONSULTATION TAXONOMY  --  11 top-level categories")
    print("  Original 80 labels  -->  11 categories (一级分类) + sub-categories (二级分类)")
    print("=" * 100)
    print(f"\n  Total records: {total:,}")
    print(f"  Original unique labels: {len(orig_counter)}")
    print(f"  New top-level categories: {len(level1_counter)}")
    print(f"  Unmapped labels: {len(unmapped)}")

    print("\n" + "-" * 100)
    print(f"{'#':>3}  {'一级分类 (CN)':<20s}  {'English Description':<46s}  {'Count':>10s}  {'Pct':>7s}  {'Subs':>4s}")
    print("-" * 100)

    rank = 0
    for cat, count in level1_counter.most_common():
        rank += 1
        en_name = ""
        n_subs = len(level2_detail[cat])
        for orig_label, (cn, en, l2) in LABEL_REMAP.items():
            if cn == cat:
                en_name = en
                break
        pct = count / total * 100
        print(f"{rank:>3}  {cat:<20s}  {en_name:<46s}  {count:>10,}  {pct:>6.2f}%  {n_subs:>4}")

    print("-" * 100)
    grand_total = sum(level1_counter.values())
    print(f"     {'TOTAL':<20s}  {'':<46s}  {grand_total:>10,}  {100:>6.2f}%")
    assert grand_total == total, f"Mismatch: grand_total={grand_total}, total={total}"

    # ─── Detailed subcategory breakdown ────────────────────────────────
    print("\n\n" + "=" * 100)
    print("  DETAILED BREAKDOWN  --  一级分类 --> 二级分类 --> 原始标签")
    print("=" * 100)

    for cat, cat_count in level1_counter.most_common():
        en_name = ""
        for orig_label, (cn, en, l2) in LABEL_REMAP.items():
            if cn == cat:
                en_name = en
                break
        pct = cat_count / total * 100
        print(f"\n{'─' * 100}")
        print(f"  [{cat}]  {en_name}")
        print(f"  Total: {cat_count:,}  ({pct:.2f}%)")
        print(f"  Sub-categories: {len(level2_detail[cat])}")
        print(f"{'─' * 100}")

        sub_cats = level2_detail[cat]
        for sub, sub_count in sub_cats.most_common():
            sub_pct = sub_count / total * 100
            cat_pct = sub_count / cat_count * 100
            print(f"    {sub:<20s}  {sub_count:>8,}  ({sub_pct:>5.2f}% of all, {cat_pct:>5.1f}% of cat)")

    # ─── Summary table ─────────────────────────────────────────────────
    print("\n\n" + "=" * 100)
    print("  SUMMARY TABLE  (for documentation)")
    print("=" * 100)
    print(f"\n{'一级分类':<20s}  {'English':<46s}  {'Count':>10s}  {'%':>7s}  Sub-cats")
    print("-" * 100)
    for cat, count in level1_counter.most_common():
        en_name = ""
        for orig_label, (cn, en, l2) in LABEL_REMAP.items():
            if cn == cat:
                en_name = en
                break
        sub_names = [s for s, c in level2_detail[cat].most_common()]
        sub_str = ", ".join(sub_names[:5])
        if len(sub_names) > 5:
            sub_str += f" ... (+{len(sub_names)-5})"
        pct = count / total * 100
        print(f"{cat:<20s}  {en_name:<46s}  {count:>10,}  {pct:>6.2f}%  {sub_str}")

    # ─── Consistency checks ────────────────────────────────────────────
    print("\n\n" + "=" * 100)
    print("  CONSISTENCY CHECKS")
    print("=" * 100)

    all_orig_labels = set(k.strip('[]') for k in orig_counter.keys())
    all_mapped_labels = set(LABEL_REMAP.keys())
    assert all_orig_labels == all_mapped_labels, \
        f"\nUnmapped: {all_orig_labels - all_mapped_labels}\nExtra: {all_mapped_labels - all_orig_labels}"
    print("  All 80 original labels are mapped. -- PASS")

    print(f"  Total from original Counter: {total:,}")
    print(f"  Total from new Level-1 Counter: {sum(level1_counter.values()):,}")
    assert total == sum(level1_counter.values()), "Count mismatch!"
    print("  Count integrity verified. -- PASS")

    print("\n  Done.\n")
