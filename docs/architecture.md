# 架构与数据流

## 一、一句话

一条 **线性但带回路** 的流水线：`输入材料 → 岗位画像 → 事实库 → 策略 → 简历 JSON → 质检回路 → 渲染 → 速查卡 → 报告`。所有中间产物都是 JSON，可读、可 diff、可人工接管。

## 二、为什么是流水线而不是"一个万能 prompt"

一个 prompt 同时做"读 JD、找事实、定策略、写文案、控字数、排一页"，模型会在几件事之间来回妥协：为了排版删掉证据、为了句式好看编数字、为了匹配关键词硬塞没做过的技能。

拆成多角色的收益：

1. **每个角色只有一个目标**，prompt 短、约束密集，输出稳定。
2. **权限隔离**：能联网的写不了简历，写简历的拿不到检索结果，从物理上杜绝"抄漂亮话"。
3. **可插拔**：换一个角色只改一份 prompt，不动流水线代码。
4. **可审计**：每个阶段落盘，出问题能定位到"哪一步把数字改错了"。

## 三、数据契约

| 阶段 | 产物 | 关键字段 |
| --- | --- | --- |
| ① JD 分析 | `steps/01_jd_profile.json` | `must_have` / `nice_to_have` / `hidden_preferences` / `keywords` / `screening_logic` |
| ② 调研 | `steps/02_research.json` | `findings[].claim/source/reliability` / `interview_process` |
| ③ 事实库 | `steps/03_facts.json` | `facts[].id/text/numbers/source/confidence/transferable` |
| ④ 定位 | `steps/04_positioning.json` | `headline` / `highlight_fact_ids` / `omit` / `risk_plan` |
| ⑤ 简历 | `steps/08_resume_final.json` | `header` + `sections[].items[]`（`role` / `bullet` / `text` 三种） |
| ⑥ 质检 | `steps/06_critic_r*.json` | `pass` / `issues[].severity/kind/where/fix` |
| 渲染 | `resume.docx/pdf/png` + `steps/09_render.json` | `pages` / `body_pt` / `attempts` |
| ⑧ 速查卡 | `interview_card.md` + `steps/10_interview_card.json` | `self_intro[]` / `questions[]` / `group_or_technical` |

### 简历结构为什么这么设计

```jsonc
{
  "header": { "name": "...", "objective": {...}, "contacts": [...], "meta": [...] },
  "sections": [
    { "id": "internship", "title": "实习经历", "en": "INTERNSHIP",
      "items": [
        // role：一行标题（组织｜角色｜时间）+ 可选说明行/技术栈行 + 若干要点
        { "type": "role", "org": "...", "role": "...", "date": "...",
          "sub": "项目名（一句话背景）", "stack": "Java · MySQL",
          "bullets": [{ "lead": "客户开发：", "text": "...", "fact_refs": ["F2"] }] },
        // bullet：单条要点（用于"核心优势""荣誉"这类列表）
        { "type": "bullet", "lead": "荣誉：", "text": "..." },
        // text：整段文字（少用，用于说明性内容）
        { "type": "text", "text": "..." }
      ] }
  ]
}
```

- `lead` 与 `text` 分开，是为了渲染时把"动作标签"加粗、正文正常，同时让质检能分别统计长度。
- `fact_refs` 是溯源锚点：质检用它对事实库，"悬空引用"直接报错。
- 三种 item 类型覆盖了中英文简历 95% 的版面需求，再加类型就要改渲染器，因此刻意保持最小集合。

## 四、控制流

```
run(cfg, inputs)
  ├─ Trace 初始化（logs/trace.jsonl）
  ├─ ① jd_analyst  ──▶ state.jd_profile
  ├─ ② researcher  ──▶ state.research_brief   （无 key 则 skip，不失败）
  ├─ ③ fact_extractor ▶ state.facts
  ├─ ④ strategist  ──▶ state.positioning
  ├─ ⑤ writer      ──▶ state.resume
  ├─ ⑥⑦ 循环 max_rounds 次：
  │     report = verify.check_resume(...)      # 确定性
  │     crit   = critic(...)                   # 语义
  │     issues = report.issues + crit.issues
  │     记录最优版本（误差数最少的那版）
  │     若 0 硬错误且无意见 → break
  │     否则 reviser(...) → 更新 state.resume
  ├─ 渲染：build_docx → docx_to_pdf → page_count → 若 >1 页则 theme.shrink() 重来（≤6 轮）
  ├─ ⑧ coach ──▶ interview_card.md
  └─ manifest.json + report.md
```

失败策略：

- **模型调用失败**：`LLMError` 被捕获，job 标记 `failed`，异常写进 `report.md` 与 `steps/`，不会静默产出半成品。
- **JSON 解析失败**：`llm.json()` 会把模型自己的输出回喂一次要求修复；仍失败则抛错。
- **没有 LibreOffice**：跳过 PDF 与页数校验，`render.note` 说明原因。
- **没有检索 key**：researcher 步骤记为 `skip`，其余照常。

## 五、渲染器

`render/docx_builder.py` 只认识 `header + sections + 三种 item`，不认识"销售"或"研发"。主题（`render/theme.py`）负责颜色、字号、边距、照片宽度；`Theme.shrink()` 用于溢出时收紧。

单页保障的三层策略：

1. **写作约束**：prompt 里限定 18–26 条要点、单条 ≤96 字。
2. **渲染收紧**：溢出时按 3.5% 递减字号与行距，最长 6 轮（字号下限 8.6pt）。
3. **可见证据**：产出 `resume.png`，人眼一眼能看出是不是挤成一团。

## 六、已知边界

- **语义夸大拦不住**。机器只能验证"数字有没有出处"，不能验证"这句话是否夸大了事实"。质检员能发现一部分，最终仍需人工读一遍 `report.md`。
- **版式只保证一页，不保证好看**。孤字换行、模块比例失衡仍需要人看一眼预览图。
- **中文断行依赖字体**。用微软雅黑在 Word 与 LibreOffice 下断行可能差 1–2 个字，因此渲染器保留了约 15pt 的底部余量。
- **不处理英文简历**。prompt 与模板都是中文优先，英文需要另写模板与文案规则。

## 七、扩展点

| 需求 | 改动 |
| --- | --- |
| 新增岗位族 | `schemas.ROLE_KEYWORDS` + `render/theme.ROLE_THEME` + `prompts/writer.md` 的模块顺序 |
| 新增规则 | `verify.py` 写函数 → `check_resume()` 挂载 |
| 新增 Agent | `agents/roles.py` 声明 + prompt 文件；如需在流水线中生效，在 `pipeline.run()` 插一段 |
| 换渲染后端（HTML/LaTeX） | 实现 `build_*` 同名函数，`render_resume` 增加 `backend` 参数 |
