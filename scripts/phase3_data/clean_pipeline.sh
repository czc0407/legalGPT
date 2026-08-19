#!/bin/bash
# 阶段三 · 数据清洗闭环
# 用法: bash scripts/phase3_data/clean_pipeline.sh
#
# 前置条件: 数据已生成（raw 数据在 data/sft/04_cards/）
# 流程: validate → auto-clean → generate audit data →
#       ⏸ 人工审核（打开 HTML 页面 → 导出 JSON）→
#       apply audit → re-validate → render → isolate → finalize
#
# 需要人工介入的步骤用 [HUMAN] 标出

set -e
SCRIPTS="scripts/phase3_data"
RAW_DIR="data/sft/04_cards"

echo "=========================================="
echo " Phase 3 · 数据清洗闭环"
echo "=========================================="

# ── Round 1: validate + auto-clean ──────────────────────────────
echo ""
echo "[1/6] 质量校验 + 自动清理..."
python $SCRIPTS/validate_raw.py --input $RAW_DIR
python $SCRIPTS/clean_dataset.py --clean-articles
# re-validate after auto-clean
python $SCRIPTS/validate_raw.py --input $RAW_DIR

# ── Generate audit data ─────────────────────────────────────────
echo ""
echo "[2/6] 生成审核数据..."
python3 -c "
import json, os, re
raw_dir = '$RAW_DIR'
raw_by_id = {}
for fname in os.listdir(raw_dir):
    if fname.endswith('.jsonl') and fname.startswith('card') and 'progress' not in fname:
        with open(os.path.join(raw_dir, fname)) as f:
            for line in f:
                d = json.loads(line.strip())
                raw_by_id[d['id']] = d
with open(os.path.join(raw_dir, 'validation_report.json')) as f:
    report = json.load(f)
def normalize(name):
    for p in ['中华人民共和国', '中国']:
        if name.startswith(p) and len(name) > len(p): return name[len(p):]
    return name
samples = []
for s in report['samples']:
    if s['has_hard'] and not s.get('auto_fixed'):
        raw = raw_by_id.get(s['id'], {})
        enriched = []
        for issue in s['hard_issues']:
            t = 'article' if '条文编号' in issue else 'law_loss' if '丢失' in issue else 'other'
            item = {'raw': issue, 'type': t}
            if t == 'law_loss':
                lm = re.search(r'丢失原始法律: {([^}]+)}', issue)
                nm = re.search(r'新增法律: {([^}]+)}', issue)
                lost = [normalize(x.strip().strip(\"'\")) for x in lm.group(1).split(',')] if lm else []
                added = [normalize(x.strip().strip(\"'\")) for x in nm.group(1).split(',')] if nm else []
                item['lost'] = lost; item['added'] = added
                item['compensated'] = [l for l in lost if l in added]
                item['real_lost'] = [l for l in lost if l not in added]
            enriched.append(item)
        samples.append({'id': s['id'], 'card': s['card'], 'answer_len': s['answer_len'],
                        'issues_enriched': enriched, 'question': raw.get('question','?'),
                        'answer': raw.get('answer','?')})
with open(os.path.join(raw_dir, 'validation_audit.json'), 'w') as f:
    json.dump(samples, f, ensure_ascii=False, indent=2)
print(f'审核数据: {len(samples)} 条 → {raw_dir}/validation_audit.json')
"

# ── Human review ─────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " [HUMAN] 请完成以下审核:"
echo "  1. 打开 http://localhost:8765/scripts/phase3_data/audit_validation.html"
echo "  2. 打开 http://localhost:8765/scripts/phase3_data/audit_refusals.html"
echo "  3. 审核完成后分别导出 JSON"
echo "  4. 将导出的文件移动到项目目录:"
echo "     mv ~/Downloads/validation_audit_fixed.json $SCRIPTS/"
echo "     mv ~/Downloads/refusal_audit.json       $SCRIPTS/"
echo ""
echo "  完成后按 Enter 继续..."
echo "=========================================="
read -p ""

# ── Apply audit results ──────────────────────────────────────────
echo ""
echo "[3/6] 应用审核结果..."
python $SCRIPTS/clean_dataset.py --audit $SCRIPTS/validation_audit_fixed.json
python $SCRIPTS/clean_dataset.py --audit $SCRIPTS/refusal_audit.json

# ── Round 2: re-validate ────────────────────────────────────────
echo ""
echo "[4/6] 重新校验（验证修复效果）..."
python $SCRIPTS/validate_raw.py --input $RAW_DIR
echo ""
echo "请检查上方输出，确认硬伤已清零或可接受。"
echo "如有新增硬伤，Ctrl+C 中止，手动处理后重新执行本脚本。"
echo "如硬伤可接受，按 Enter 继续..."
read -p ""

# ── Render + Isolate + Finalize ──────────────────────────────────
echo ""
echo "[5/6] 渲染 SFT + 检查隔离..."
python $SCRIPTS/render_sft.py
python $SCRIPTS/check_isolation.py

# 移除评测集重叠样本
echo ""
python3 -c "
import json, re, hashlib
def fp(t): return hashlib.md5(re.sub(r'[^\w]', '', t.lower().replace(' ','')).encode()).hexdigest()
overlaps = {'我就一个孩子，没有一孩证，以过生育年龄，能不能享受国家的补贴吗吗？',
            '我在总公司上班，合同在分公司，却没在分公司上一天班，分公司也没给我一分钱我告的是总公司对吗？'}
fps = {fp(q) for q in overlaps}
with open('data/sft/05_train/train.jsonl') as f: data = [json.loads(l) for l in f if l.strip()]
clean = [d for d in data if fp(d.get('input',d.get('question',''))) not in fps]
print(f'移除评测集重叠: {len(data)-len(clean)} 条')
with open('data/sft/05_train/train.jsonl','w') as f:
    for d in clean: f.write(json.dumps(d,ensure_ascii=False)+'\n')
"

echo ""
echo "[6/6] 冻结..."
python $SCRIPTS/finalize_dataset.py

echo ""
echo "=========================================="
echo " 数据集清洗完成！"
echo "=========================================="
