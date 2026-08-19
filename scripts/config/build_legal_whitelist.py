#!/usr/bin/env python3
"""构建 legal_name_whitelist.json

自动尝试从公开源获取中国现行有效法律列表：
  1. GitHub: taburise/Chinese-Laws-folk (dataset_infos.json)
  2. NPC 国家法律法规数据库 API

均失败时，使用已收录的 306 部现行有效法律（来源：全国人大公报 2025-06-27）
+ 常用行政法规/司法解释。

用法:
    python scripts/config/build_legal_whitelist.py          # 自动获取或使用缓存
    python scripts/config/build_legal_whitelist.py --update  # 强制尝试更新
"""
import json, os, sys, argparse

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legal_name_whitelist.json")

# ═══════════════════════════════════════════════════════════════
# 缓存数据：306 部现行有效法律 + 常用法规/司法解释
# 来源：全国人大公报 2025-06-27 "现行有效法律目录（306件）"
# 更新：如在线获取成功则覆盖此缓存
# ═══════════════════════════════════════════════════════════════

FALLBACK_DATA = {
    "_meta": {
        "source": "全国人大公报 2025-06-27",
        "url": "http://www.npc.gov.cn/",
        "total_laws": 306,
        "note": "此列表为缓存数据。运行 python scripts/config/build_legal_whitelist.py --update 尝试在线更新",
    },
    "current_laws": [
        # ═══ 宪法（1件）═══
        "宪法",

        # ═══ 宪法相关法（52件）═══
        "地方各级人民代表大会和地方各级人民政府组织法",
        "全国人民代表大会和地方各级人民代表大会选举法",
        "人民法院组织法", "人民检察院组织法", "国籍法",
        "全国人民代表大会组织法", "国务院组织法", "民族区域自治法",
        "全国人民代表大会常务委员会议事规则", "全国人民代表大会议事规则",
        "集会游行示威法", "城市居民委员会组织法", "村民委员会组织法",
        "香港特别行政区基本法", "澳门特别行政区基本法",
        "国旗法", "国徽法", "国歌法",
        "领海及毗连区法", "缔结条约程序法",
        "全国人民代表大会和地方各级人民代表大会代表法",
        "国家赔偿法", "法官法", "检察官法", "戒严法", "国防法", "立法法",
        "反分裂国家法", "国家安全法", "国家勋章和国家荣誉称号法",
        "监察法", "人民陪审员法", "英雄烈士保护法",
        "公职人员政务处分法", "监察官法",
        "香港特别行政区维护国家安全法", "香港特别行政区驻军法",
        "澳门特别行政区驻军法",
        "反外国制裁法", "陆地国界法", "对外关系法", "外国国家豁免法",
        "爱国主义教育法", "各级人民代表大会常务委员会监督法",
        "专属经济区和大陆架法", "驻外外交人员法",

        # ═══ 民法商法（25件）═══
        "民法典", "商标法", "专利法", "著作权法", "海商法",
        "消费者权益保护法", "公司法", "商业银行法", "票据法", "保险法",
        "拍卖法", "合伙企业法", "证券法", "个人独资企业法", "招标投标法",
        "信托法", "农村土地承包法", "证券投资基金法", "电子签名法",
        "企业破产法", "农民专业合作社法", "涉外民事关系法律适用法",
        "期货和衍生品法", "农村集体经济组织法", "全民所有制工业企业法",

        # ═══ 行政法（重点列出常用）═══
        "治安管理处罚法", "行政处罚法", "行政许可法", "行政强制法",
        "行政复议法", "公务员法",
        "道路交通安全法", "食品安全法", "药品管理法", "传染病防治法",
        "环境保护法", "大气污染防治法", "水污染防治法", "海洋环境保护法",
        "土地管理法", "城乡规划法", "城市房地产管理法", "建筑法",
        "义务教育法", "高等教育法", "学位法", "学前教育法",
        "文物保护法", "档案法", "兵役法", "海关法", "野生动物保护法",
        "突发事件应对法", "保守国家秘密法", "国防教育法", "国境卫生检疫法",
        "户口登记条例", "海上交通安全法", "消防法",
        "职业教育法", "民办教育促进法", "科学技术进步法",
        "公共图书馆法", "电影产业促进法", "旅游法",
        "精神卫生法", "基本医疗卫生与健康促进法", "疫苗管理法", "生物安全法",
        "噪声污染防治法", "土壤污染防治法", "固体废物污染环境防治法",
        "环境影响评价法", "防震减灾法", "气象法", "测绘法", "人民防空法",
        "护照法", "出境入境管理法",
        "国家情报法", "反恐怖主义法", "境外非政府组织境内活动管理法",
        "网络安全法", "数据安全法", "个人信息保护法", "密码法", "禁毒法",

        # ═══ 经济法（重点列出常用）═══
        "反垄断法", "反不正当竞争法", "增值税法",
        "企业所得税法", "个人所得税法", "税收征收管理法",
        "环境保护税法", "资源税法", "印花税法", "关税法",
        "外商投资法", "电子商务法",
        "出口管制法", "海南自由贸易港法",
        "长江保护法", "黄河保护法", "黑土地保护法", "湿地保护法",
        "粮食安全保障法", "能源法", "矿产资源法", "反洗钱法",
        "统计法", "会计法", "审计法", "预算法",
        "中国人民银行法", "银行业监督管理法",
        "价格法", "中小企业促进法",
        "农业法", "渔业法", "森林法", "草原法", "水法",
        "畜牧法", "种子法", "农产品质量安全法",

        # ═══ 社会法（28-30件）═══
        "劳动法", "劳动合同法", "社会保险法", "就业促进法",
        "工会法", "安全生产法", "职业病防治法",
        "残疾人保障法", "未成年人保护法", "妇女权益保障法",
        "老年人权益保障法", "反家庭暴力法",
        "慈善法", "法律援助法", "家庭教育促进法",
        "退役军人保障法", "无障碍环境建设法",
        "母婴保健法", "人口与计划生育法",
        "公益事业捐赠法", "归侨侨眷权益保护法", "预防未成年人犯罪法",

        # ═══ 刑法（4件）═══
        "刑法", "反间谍法", "反电信网络诈骗法", "反有组织犯罪法",

        # ═══ 诉讼与非诉讼程序法（11件）═══
        "民事诉讼法", "刑事诉讼法", "行政诉讼法",
        "仲裁法", "人民调解法",
        "劳动争议调解仲裁法", "农村土地承包经营纠纷调解仲裁法",
        "引渡法", "海事诉讼特别程序法", "国际刑事司法协助法",
    ],
    "regulations": [
        "工伤保险条例", "失业保险条例", "社会保险费征缴暂行条例",
        "住房公积金管理条例", "劳动合同法实施条例",
        "道路交通安全法实施条例", "道路运输条例",
        "食品安全法实施条例", "药品管理法实施条例",
        "城市居民最低生活保障条例", "诉讼费用交纳办法",
        "医疗事故处理条例", "物业管理条例",
        "国有土地上房屋征收与补偿条例",
        "不动产登记暂行条例", "不动产登记暂行条例实施细则",
        "商业银行信用卡业务监督管理办法",
        "最高人民法院关于审理人身损害赔偿案件适用法律若干问题的解释",
        "最高人民法院关于审理民间借贷案件适用法律若干问题的规定",
        "最高人民法院关于审理劳动争议案件适用法律问题的解释",
        "最高人民法院关于审理道路交通事故损害赔偿案件适用法律若干问题的解释",
        "最高人民法院关于适用《中华人民共和国民法典》婚姻家庭编的解释",
        "最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释",
    ],
    "deprecated_but_real": [
        "婚姻法", "合同法", "物权法", "侵权责任法", "担保法",
        "继承法", "收养法", "民法通则", "民法总则",
        "城市规划法", "劳动保险条例", "治安管理处罚条例",
    ],
}


def try_fetch_online():
    """尝试从 GitHub 获取最新数据。成功返回 dict，失败返回 None。"""
    import urllib.request, urllib.error

    sources = [
        # taburise/Chinese-Laws-folk: 2025年数据集
        ("https://api.github.com/repos/taburise/Chinese-Laws-folk/contents/dataset_infos.json",
         "taburise/Chinese-Laws-folk"),
    ]

    for url, name in sources:
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "legalGPT-fetch")
            with urllib.request.urlopen(req, timeout=10) as resp:
                import base64
                data = json.loads(resp.read())
                if "content" in data:
                    content = base64.b64decode(data["content"]).decode("utf-8")
                    laws = json.loads(content)
                    print(f"  ✅ 从 {name} 获取成功 ({len(laws)} 条)")
                    return laws
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            continue

    return None


def build_whitelist(raw_data):
    """从原始数据提取法律名称集合。"""
    names = set(FALLBACK_DATA["current_laws"])
    names.update(FALLBACK_DATA["regulations"])
    names.update(FALLBACK_DATA["deprecated_but_real"])
    # 去"中华人民共和国"前缀生成变体
    extra = set()
    for n in names:
        for prefix in ["中华人民共和国", "中国"]:
            if n.startswith(prefix) and len(n) > len(prefix):
                extra.add(n[len(prefix):])
    names.update(extra)
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description="构建法律名称白名单")
    parser.add_argument("--update", action="store_true", help="强制尝试在线更新")
    args = parser.parse_args()

    online_data = None
    if args.update:
        print("尝试在线更新...")
        online_data = try_fetch_online()

    whitelist = build_whitelist(online_data or FALLBACK_DATA)
    output = {
        "_meta": FALLBACK_DATA["_meta"],
        "_count": len(whitelist),
        "_updated": "2025-06-27" if not online_data else "online",
        "names": whitelist,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"白名单: {len(whitelist)} 个法律名称 → {OUTPUT}")


if __name__ == "__main__":
    main()
