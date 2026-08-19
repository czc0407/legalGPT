# LegalGPT 文档说明

## 文档职责

| 文档 | 职责 | 读者 | 更新时机 |
|------|------|------|------|
| `LegalGPT-postTraing-Spec.md`（主 spec） | **最终设计方案的权威记录**。记录所有已确认的设计决策、技术选型、评测体系。不记录方案迭代过程。 | 项目 Owner、面试官 | 重大决策确定后 |
| `docs/superpowers/specs/phase*-design.md` | **各阶段的详细设计文档**。只保留最终方案，不保留废弃尝试和迭代过程。 | 执行者 | 设计方案确定后 |
| `project-log/phase-*-*/log.md` | **各阶段的实现日志**。记录实现过程、迭代调试、改动原因、思考过程、踩坑记录。是设计文档的补充。 | 作者本人、后续接手者 | 过程中随时更新 |
| `docs/handoff/*.md` | **每日/每次会话的交接文档**。记录当前状态、今日完成、待决策项、运行中任务。会话结束前写。 | 下次会话的自己 | 每次会话结束前 |
| `docs/superpowers/plans/*-plan.md` | **实施计划**。将设计文档拆解为可执行的 task 列表。设计确定后写，执行完成前更新。 | 执行者 | 设计确定后 |

## 三种文档的关系

```
主 spec (最终方案)
  ├──→ phase-design (某阶段的详细设计，只保留最终版)
  │       ├── 参考: phase-log (该阶段的实现日志)
  │       └──→ plan (实施计划)
  │
  └──→ handoff (会话级交接，短期)
```

## 如何更新

1. **确定一个新方案** → 更新主 spec
2. **某个阶段的详细设计确定** → 更新 phase-design（删掉废弃尝试，只保留最终方案）
3. **设计迭代了、踩坑了、推翻了** → 写进 log（保留思考过程）
4. **今天的讨论和决定** → 写进 handoff（下次会话的起点）
5. **计划怎么执行** → 写进 plan

## 现有文档清单

| 文件 | 职责 | 最后更新 |
|------|------|------|
| `LegalGPT-postTraing-Spec.md` | 项目总 spec | 2026-08-03 |
| `docs/superpowers/specs/phase1-eval-harness-design.md` | 阶段一：评测框架设计 | 2026-07-21 |
| `docs/superpowers/specs/phase2-eval-set-baseline-design.md` | 阶段二：评测集+Baseline 设计 | 2026-08-04 |
| `docs/superpowers/specs/phase3-dataset-design.md` | 阶段三：训练数据集设计 | 2026-07-30 |
| `project-log/phase-01-eval-harness/log.md` | 阶段一：实现日志 | 2026-07-21 |
| `project-log/phase-02-eval-baseline/log.md` | 阶段二：实现日志 | 2026-08-04 |
| `docs/handoff/*.md` | 各日交接文档 | 2026-08-02 |

## 文档审查清单（写/改文档前自查）

- [ ] 这是设计决策还是迭代记录？→ 决策进 design/spec，记录进 log
- [ ] 这是今天的状态还是长期事实？→ 短期进 handoff，长期进 spec
- [ ] 我是不是在 design 里写了太多"我们试过 X 但不行"？→ 移到 log
- [ ] 我是不是在 log 里只写了结果没写原因？→ log 的价值在过程和原因
- [ ] 改了这个文档后，有没有关联文档需要同步更新？→ 主 spec 是下游，log 是上游
