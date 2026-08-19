# LegalGPT — 法律咨询大模型后训练

基于 **Qwen2.5-7B-Instruct** 的法律咨询领域后训练项目，打通 **SFT → DPO** 完整链路，在无 RAG 场景下将通用大模型迁移为专业法律咨询助手——具备结构化推理、信息不足时追问、超出能力时礼貌拒答的能力。

## 核心成果

| 指标 | M0 基座 | SFT V4 | DPO Round 5 V1 | 提升 |
|------|:---:|:---:|:---:|:---:|
| 准确性 | 77% | 92.5% | **94.1%** | +1.6% |
| 审慎度（0-3）| 0.9 | 0.93 | **1.24** | +33% |
| 拒答质量（0-3）| 0.1 | 0.13 | **0.57** | +338% |
| Layer 1 法律知识保真度 | 29.2% | 34.6% | **37.8%** | +8.6pct |

> **最终成果 DPO Round 5 V1**：审慎度 +0.31、拒答 +0.44，准确性零退化；Layer 1 法律知识不退化反而逐段提升（SFT +5.4pct、DPO 再 +3.2pct）。

### 评测体系

评测分两层，其中 **Layer 2（咨询质量）是本项目自建的核心**：

- **Layer 1 法律知识保真度**：复用 [DISC-Law-Eval](https://github.com/FudanDISC/DISC-LawLLM) 客观选择题 2,563 道，作"负面守门员"——SFT/DPO 后知识不应显著下降（本项目实测不退化反而逐段提升）。
- **Layer 2 咨询质量（自建 4-Panel）**：
  - 发现 LLM 盲评 Judge 系统性失效（GPT-4o-mini 对 115 条回答 43% 满分、0% 低于 3 分，连带【注】自语的垃圾都打 5.0），定位"参考答案是 LLM-Judge 可靠的前提"——Judge 只做语义一致性对比，不做独立法律判断。
  - 7 项规则检测 + Checklist 对比专家参考答案（satisfied/violated/unknown）+ 质量/行为 0-3 打分，四面板独立报告、不合成总分。
  - 任务分类从六类收敛到两类（类型 5 数据不存在、类型 4 分类不可靠、类型 3 评测不可行）。
  - Judge 校准：30 条试点 + Cohen's Kappa（扣偶然一致）+ Spearman ρ（防 Kappa paradox），冻结 240 条评测集（DISC 改写 80 + 概念 50 + 行为 110）。

## 为什么做

1. **现有法律微调模型质量一般，有明确改进空间**。两个有代表性的开源法律微调模型都存在明显缺陷：
   - **DISC-LawLLM**（复旦）：典型的"问题→法条→结论"一步式回答，41.7% 篇幅不足 200 字、88.2% 推理信号缺失——只有结论没有推演（如"根据《城乡规划法》，农田建棚属于违法建筑"直接甩结论）。
   - **Lawyer-LLaMA**（zixun_gpt4 数据）：公式化模板严重，31.3% 含"首先/其次/最后"标签词、32.4% 以"建议咨询律师"等套话收尾——读完不知道下一步该做什么。
2. **有一类 SFT 解决不了的边界行为**：信息不足该追问、超出能力该拒答——与 SFT 最大化 P(answer|question) 存在结构性冲突，恰好是 DPO 的价值所在。

## 技术方案

- **基座**：Qwen2.5-7B-Instruct，LoRA 微调（rank=32、alpha=64、q_proj+v_proj）
- **SFT**：8k 条 canonical 格式数据（6 卡规格 + deepseek-chat 生成 + 三级质量校验 + 训评指纹隔离），统一"理解处境→法律定性→说理→建议"的推理范式
- **DPO**：2019 对偏好对（deepseek-chat 生成 chosen + SFT 真实输出作 rejected），beta 0.5；5 轮迭代，最终收敛出"chosen 贴近 SFT 风格 → 初始 margin 为正"的成功配方
- **评测**：自建 4-Panel 评测体系（7 项规则检测 + Checklist 对比专家参考答案 + 质量/行为 0-3 打分），240 条冻结评测集，LLM-as-Judge 校准（Cohen's Kappa + Spearman ρ）

## 复用的项目与资源

| 资源 | 用途 |
|------|------|
| [DISC-LawLLM](https://github.com/FudanDISC/DISC-LawLLM)（复旦）| DISC-Law-SFT 训练数据（重写为 canonical）+ DISC-Law-Eval 评测集（Layer 1 知识保真度）+ bare prompt 评测思路 |
| [华律网](https://www.66law.cn/) | 法律咨询问题源（58 万条清洗池，SFT 卡 1/2 + 拒答数据）|
| Lawyer-LLaMA（zixun_gpt4 数据）| 训练数据（重写去公式化）|
| [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) | SFT + DPO 训练框架 |
| [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | 基座模型 |
| deepseek-chat / GPT-4o-mini | 训练数据生成 / LLM-as-Judge |

## 模型

15 个 LoRA 适配器已上传 Hugging Face（`Lexiiiii/legalgpt-*`）：

| 模型 | 说明 |
|------|------|
| [legalgpt-dpo-round5-v1](https://huggingface.co/Lexiiiii/legalgpt-dpo-round5-v1) | **最终成果**（DPO Round 5 V1）|
| [legalgpt-sft-full](https://huggingface.co/Lexiiiii/legalgpt-sft-full) | SFT 全量基线 |
| 其余 13 个 adapter | 各轮训练（含 beta 消融、失败中间轮）|

## 快速开始

加载最终模型（LoRA 适配器 + 基座）：

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
model = PeftModel.from_pretrained(base, "Lexiiiii/legalgpt-dpo-round5-v1")
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")

messages = [
    {"role": "system", "content": "你是一名中国法律专家。"},
    {"role": "user", "content": "公司拖欠工资三个月，没有签劳动合同，现在要求我离职，我应该怎么办？"},
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=400, temperature=0.7, do_sample=True)
print(tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True))
```

## 目录结构

```
legalGPT/
├── configs/          # LLaMA-Factory 训练配置（SFT + DPO 各轮）
├── eval/             # 评测框架（4-Panel + 规则检测 + Layer 1）
├── scripts/          # 数据构造 / 训练脚本（按 phase 分目录）
├── docs/             # 设计文档 + 总 spec
├── project-log/      # 各阶段实现日志
└── data/             # 训练数据（gitignored，需本地生成）
```

## 复现

- 总设计：[docs/LegalGPT-postTraing-Spec.md](docs/LegalGPT-postTraing-Spec.md)
- 各阶段设计：[docs/superpowers/specs/](docs/superpowers/specs/)
- 实现日志：[project-log/](project-log/)

## License

[Apache-2.0](LICENSE)
