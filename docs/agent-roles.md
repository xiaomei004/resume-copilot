# Agent 角色与权限

## 一、设计原则

1. **角色单一**：一个 Agent 只输出一种决策，不越界（策略师只定策略、撰写员只写文案）。
2. **权限最小化**：默认什么都不能读。需要 JD 的显式给 `read_jd`，需要联网的显式给 `search_web`。
3. **读写分离**：写简历的（writer / reviser）没有联网权限；能联网的（researcher）不能写简历。
4. **批评与修改分离**：critic 只能出问题，不能给成品；否则会退化成"自己夸自己改过的稿"。

## 二、角色表

| # | Agent（key） | Prompt | 权限 | 温度 | 输入 | 输出 | 失败会怎样 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ① | JD 分析员 `jd_analyst` | `jd_analyst.md` | `read_jd` | 默认 | JD 原文 + 岗位提示 | 岗位画像（硬门槛/加分/隐含偏好/关键词/筛人逻辑/风险） | 抛错，job 失败；不会用旧简历猜测 JD |
| ② | 调研员 `researcher` | `researcher.md` | `read_jd` `search_web` `read_research` | 0.2 | 岗位画像 + 检索结果 | 带来源与可信度的结论、面试流程、简历建议、反问 | 无 key 时整步 `skip`；有 key 但无结果时写 `gaps` |
| ③ | 事实库构建员 `fact_extractor` | `fact_extractor.md` | `read_resume` | 0.1 | 旧简历 + 补充信息 | 原子事实（含数字/来源/可信度/可迁移性） | 抛错；事实是地基，不能空着跑 |
| ④ | 定位策略师 `strategist` | `strategist.md` | `read_jd` `read_facts` `read_research` | 0.5 | 画像 + 事实库 + 简报 | 主线叙事、差异化、强调/删减清单、风险化解方案 | 抛错；宁可失败也不让 writer 盲写 |
| ⑤ | 简历撰写员 `writer` | `writer.md` + `writer.<family>.md` | `write_resume`（读 JD/事实/策略） | 0.35 | 策略 + 事实库 | 结构化简历 JSON | 抛错；JSON 异常会先自动修复一次 |
| ⑥ | 质检员 `critic` | `critic.md` | `read_jd` `read_resume` `read_facts` | 0.2 | 简历 + 事实 + 机器检查结果 | `pass` + issues（severity/kind/where/fix） | 抛错则以机器报告单独判定 |
| ⑦ | 修订员 `reviser` | `reviser.md` + `writer.<family>.md` | `write_resume` | 0.25 | 简历 + issues + 事实库 + 未覆盖关键词 | 同 schema 的简历 JSON | 抛错则保留上一版（记录在 manifest） |
| ⑧ | 面试教练 `coach` | `coach.md` + `coach.<family>.md` | `read_resume` | 0.6 | 最终简历 + 画像 + 简报 | 速查卡（口播稿/问题/群面或技术追问/清单） | 抛错则简历照常交付，速查卡标记缺失 |

## 二之二、Prompt 变体怎么解析

```
resolve_prompts(spec, role_family):
    chain = [spec.prompt_file]
    if 存在 f"{stem}.{role_family}.md":   chain.append(该变体)
    return chain
```

- 底座（`writer.md`）放岗位无关的内容：版式硬约束、JSON schema、事实边界、四类禁止补的内容。
- 变体（`writer.*.md` / `coach.*.md`）只放岗位相关的判断标准与裁剪规则，**不重复 schema**。
- `reviser` 通过 `variant_stem="writer"` 复用撰写员的岗位变体，改稿时不会忘掉岗位规则。
- 变体缺失时自动退回底座，因此新增岗位族不会打断老流程。
- `trace.jsonl` 里每个 Agent 事件都记了 `prompts=writer.md/writer.rnd.md`，方便复盘"这一稿是哪两份 prompt 合成的"。

## 三、权限矩阵

| 权限 | ① | ② | ③ | ④ | ⑤ | ⑥ | ⑦ | ⑧ |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `read_jd` | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `read_facts` | | | | ✓ | ✓ | ✓ | ✓ | |
| `read_resume` | | | ✓ | | | ✓ | ✓ | ✓ |
| `read_research` | | ✓ | | ✓ | ✓ | | | ✓ |
| `search_web` | | ✓ | | | | | | |
| `write_resume` | | | | | ✓ | | ✓ | |

（`read_resume` 给 writer 是隐含的：它要读策略里引用的内容；实际传给 writer 的是事实库与策略，不是原始简历。）

## 四、为什么不让 researcher 写简历

检索到的行业话术、竞品话术、面经黑话，看起来很专业，但**不是这个人的事实**。一旦让同一个角色既检索又撰稿，模型会把"行业里通常这么说"写进简历，面试官一追问就穿帮。

物理隔离后，researcher 的产出只能作为 `research_brief` 影响策略（讲哪个故事），不能变成句子。这条规则在代码里体现为：`writer` 的 messages 里根本没有检索原文，只有 `facts` 与 `positioning`。

## 五、加一个新角色要做什么

```python
# 1) agents/roles.py
MY_AGENT = AgentSpec(
    key="my_agent",
    title="我的角色",
    prompt_file="my_agent.md",
    permissions=(Perm.READ_FACTS,),
    temperature=0.3,
    note="一句话说明边界",
)

# 2) 写 prompts/my_agent.md（角色 / 输入 / 硬约束 / JSON schema）
# 3) 在 pipeline.run() 里插一段：agents.call_agent(MY_AGENT, ctx, vars, post=normalize)
```

不需要改编排器结构，也不需要改渲染器。
