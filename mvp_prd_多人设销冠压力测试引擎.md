# 多人设销冠压力测试引擎 MVP PRD

版本：v0.1  
文档类型：MVP 产品需求文档 PRD  
适用阶段：第一版测试引擎开发  
目标形态：命令行 / 本地脚本优先，暂不开发完整 Web 平台  
核心目标：用最小工程成本验证四 Agent 销售模拟引擎是否能稳定产出高质量对话、复盘、话术候选和培训洞察。

---

# 1. 项目背景

## 1.1 背景说明

当前目标是搭建一个“多人设销冠压力测试引擎”的 MVP，用于模拟不同用户人设与销冠 Agent 的多轮销售对话。

系统不是为了做一个普通聊天机器人，而是为了验证以下业务假设：

1. 不同用户人设可以基于同一产品产生不同异议路径。
2. 销冠 Agent 可以基于产品资料、当前会话画像和 Judge 指令进行更具体的销售回应。
3. Judge Agent 可以在会中控制对话阶段、防止假成交、减少重复废话。
4. Coach Agent 可以在会后提炼出可复用销售资产。
5. 最终输出可以服务销售培训、产品培训、FAQ 优化、竞品攻防话术和 Training Guide 生成。

## 1.2 为什么先做 MVP

完整系统包含 LangGraph、RAG、SQLite、经验库、FastAPI、WebSocket、Vue 看板、统计大屏等能力。完整开发成本较高，不适合第一阶段直接投入。

MVP 阶段只验证核心引擎：

```text
Persona Agent
+ Sales Champion Agent
+ Judge Agent
+ Coach Agent
+ 阶段驱动对话
+ 当前会话画像
+ 本地文件输入输出
```

第一版不要被 Web 界面、实时推流、CRUD、统计大屏拖死。人类工程项目最常见的死法，就是还没证明发动机能转，就先研究车漆颜色。

---

# 2. 项目定位

## 2.1 产品名称

中文名：多人设销冠压力测试引擎 MVP  
英文名：Sales Simulation Engine MVP

## 2.2 一句话定义

一个基于四 Agent 的本地销售模拟测试引擎：读取产品资料和用户人设，自动生成 20-50 轮销售博弈对话，并输出会后复盘、用户异议、有效回应、失败回应、话术候选和培训洞察。

## 2.3 MVP 不做什么

MVP 不做以下内容：

1. 不做完整 Web 看板。
2. 不做实时 WebSocket token 流。
3. 不做完整 FastAPI 服务。
4. 不做多人协作权限。
5. 不做正式经验库管理 UI。
6. 不做复杂统计大屏。
7. 不做自动经验正式入库。
8. 不做多产品复杂配置后台。
9. 不做向量库高级召回优化。
10. 不做生产级部署。

这些不是不重要，而是现在做会导致第一版变成一只长满功能但不会走路的怪物。

---

# 3. MVP 核心目标

## 3.1 产品目标

MVP 的产品目标是：

```text
在本地通过一条命令运行一场销售模拟，输入产品资料和用户人设，输出完整对话与结构化复盘结果。
```

## 3.2 验证目标

MVP 必须验证以下问题：

| 编号 | 验证问题 | 通过标准 |
|---|---|---|
| V1 | Persona Agent 是否能扮演真实用户，而不是配合型 AI | 前 5 轮不轻易成交，能持续提出异议 |
| V2 | Sales Agent 是否能具体回应用户问题 | 回应包含用户上下文和产品信息，不只是泛泛推销 |
| V3 | Judge Agent 是否能控制对话质量 | 能输出阶段、问题、下一步指令、避免重复项 |
| V4 | Session Memory 是否能减少失忆 | 后续回应不会重复用户已拒绝建议 |
| V5 | Coach Agent 是否能提炼业务资产 | 输出异议、有效回应、失败回应、话术候选、培训洞察 |
| V6 | 输出是否可用于后续 Training Guide | script_candidates.md 具备可直接复用内容 |

## 3.3 第一版成功标准

MVP 第一版完成后，至少达到以下标准：

1. 能稳定运行 1 场 20 轮以上对话。
2. 能读取 1 个产品资料文件。
3. 能读取 1 个用户人设 YAML。
4. 能自动进行阶段推进。
5. 能每 3-5 轮调用 Judge。
6. 能每 3-5 轮更新当前会话画像。
7. 能输出 dialogue.json。
8. 能输出 review.json。
9. 能输出 script_candidates.md。
10. Coach 输出中至少包含：
   - 3 条用户异议
   - 3 条有效回应或改进回应
   - 3 条培训洞察
   - 5 条可复用话术候选

---

# 4. 用户与使用场景

## 4.1 目标用户

### 4.1.1 主要用户

1. AI 项目开发者
2. 销售培训负责人
3. 产品培训负责人
4. 话术设计人员
5. 企业 AI 培训讲师
6. Agent 工作流设计者

### 4.1.2 当前 MVP 的直接使用者

当前 MVP 的直接使用者是开发者本人，通过 Cursor / 命令行运行脚本，查看输出文件。

## 4.2 使用场景

### 场景 1：测试某产品销售话术

用户准备一个产品资料 `product.md`，选择一个人设，例如“价格敏感学生”，运行模拟，查看这个用户会提出哪些异议，销冠如何回应，最终是否成交。

### 场景 2：挖掘用户异议

通过多个 Persona 批量模拟，发现不同用户类型对同一产品的常见顾虑，例如价格、竞品、售后、使用难度、信任不足。

### 场景 3：生成销售培训素材

从模拟对话中提炼：

1. 标准话术
2. 错误示范
3. 异议处理方法
4. FAQ 追问回答
5. 成交推进话术

### 场景 4：作为 AI 培训案例

把系统作为企业 AI 培训中的案例，展示如何从单 Prompt 生成升级到多 Agent 工作流。

---

# 5. MVP 总体流程

## 5.1 运行前准备

用户需要准备：

```text
1. 产品资料：data/product.md
2. 用户人设：personas/xxx.yaml
3. 模型 API Key：.env
4. 运行参数：max_rounds、judge_interval、memory_interval
```

## 5.2 运行命令

MVP 推荐命令：

```bash
python -m src.runner \
  --product data/product.md \
  --persona personas/price_sensitive_student.yaml \
  --topic "学习平板销售模拟" \
  --max-rounds 20
```

## 5.3 主流程

```text
1. 加载配置
2. 读取产品资料
3. 读取 Persona YAML
4. 初始化 DialogueState
5. Persona Agent 生成用户发言
6. 更新 recent_history
7. Sales Agent 读取产品资料、当前会话画像、Judge 指令，生成回应
8. 保存本轮对话
9. 每 N 轮调用 Session Memory 更新器
10. 每 N 轮调用 Judge Agent
11. Judge 判断是否继续、是否切换阶段、是否结束
12. 达到结束条件后调用 Coach Agent
13. 输出 dialogue.json
14. 输出 review.json
15. 输出 script_candidates.md
16. 将 candidate_lessons 追加写入 lessons_candidate.jsonl
```

---

# 6. MVP 功能范围

## 6.1 P0 必须功能

| 模块 | 功能 | 优先级 |
|---|---|---|
| 配置模块 | 读取 .env 和模型配置 | P0 |
| 产品资料模块 | 读取 product.md | P0 |
| Persona 模块 | 读取 YAML 人设 | P0 |
| Persona Agent | 生成真实用户发言 | P0 |
| Sales Agent | 生成销冠回应 | P0 |
| Judge Agent | 阶段判断与质量控制 | P0 |
| Session Memory | 当前会话画像更新 | P0 |
| Coach Agent | 会后复盘与资产提取 | P0 |
| Runner | 单场会话运行 | P0 |
| 输出模块 | dialogue.json / review.json / script_candidates.md | P0 |

## 6.2 P1 增强功能

| 模块 | 功能 | 优先级 |
|---|---|---|
| 批量运行 | 多 Persona 批量跑 | P1 |
| 简易检索 | 从 product.md 中按关键词截取相关段落 | P1 |
| 指标统计 | 计算异议数量、有效回应数量、话术数量 | P1 |
| 候选经验库 | lessons_candidate.jsonl 追加写入 | P1 |
| 日志 | 控制台展示每轮进度 | P1 |

## 6.3 暂不做功能

| 模块 | 功能 | 原因 |
|---|---|---|
| Web UI | Vue 看板 | 非核心验证项 |
| FastAPI | 接口服务 | MVP 本地脚本足够 |
| WebSocket | 实时推流 | 第一版没必要 |
| Chroma | 正式向量库 | 可以第二阶段加 |
| SQLite | 正式数据库 | 第一版 JSON 文件足够 |
| 自动经验入库 | approved lessons | 容易污染知识库 |
| 统计大屏 | 趋势分析 | 没有足够数据前是装饰品 |

---

# 7. 系统模块设计

## 7.1 目录结构

MVP 推荐目录：

```text
sales_game_mvp/
├── .env
├── .env.example
├── requirements.txt
├── README.md
├── data/
│   ├── product.md
│   ├── sessions/
│   └── lessons_candidate.jsonl
├── personas/
│   ├── price_sensitive_student.yaml
│   ├── skeptical_parent.yaml
│   └── tech_enthusiast.yaml
├── prompts/
│   ├── persona_prompt.md
│   ├── sales_prompt.md
│   ├── judge_prompt.md
│   ├── coach_prompt.md
│   └── session_memory_prompt.md
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── llm.py
│   ├── schema.py
│   ├── loaders.py
│   ├── agents.py
│   ├── memory.py
│   ├── judge.py
│   ├── coach.py
│   ├── output.py
│   ├── runner.py
│   └── utils.py
└── outputs/
    └── .gitkeep
```

---

# 8. 数据结构设计

## 8.1 Persona YAML

### 示例

```yaml
id: price_sensitive_student
name: 价格敏感学生
age: 21
occupation: 大学生
budget: 2500
personality: 谨慎、直接、对价格敏感
pain_points:
  - 想买设备辅助学习
  - 预算有限
  - 担心买贵了
objection_style: 喜欢反复比较价格，会询问竞品和优惠
purchase_goal: 找到性价比最高的选择
pressure_profile:
  price_sensitivity: 0.9
  trust_threshold: 0.7
  patience: 0.4
  competitor_awareness: 0.8
  decision_power: 0.5
  emotion_volatility: 0.6
  need_urgency: 0.7
  skepticism: 0.8
  bargaining_aggressiveness: 0.9
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | 是 | 人设唯一 ID |
| name | string | 是 | 人设名称 |
| age | number | 否 | 年龄 |
| occupation | string | 否 | 职业 |
| budget | number/string | 否 | 预算 |
| personality | string | 是 | 性格描述 |
| pain_points | list | 是 | 痛点列表 |
| objection_style | string | 是 | 异议风格 |
| purchase_goal | string | 是 | 购买目标 |
| pressure_profile | object | 是 | 压力参数 |

---

## 8.2 DialogueState

MVP 中的核心状态对象：

```python
from typing import TypedDict, List, Dict, Any, Optional

class DialogueState(TypedDict):
    session_id: str
    topic: str
    product_text: str
    product_summary: str
    persona_profile: Dict[str, Any]
    round_idx: int
    max_rounds: int
    current_stage: str
    outcome: str
    recent_history: List[Dict[str, Any]]
    full_history: List[Dict[str, Any]]
    session_memory: Dict[str, Any]
    judge_feedback: Dict[str, Any]
    coach_review: Optional[Dict[str, Any]]
```

---

## 8.3 Turn 数据结构

```json
{
  "idx": 1,
  "speaker": "persona",
  "content": "我主要想买来上课记笔记，但预算不太高。",
  "metadata": {
    "intent": "initial_need",
    "attitude": "cautious",
    "purchase_signal": 0.3,
    "status": "CONTINUE"
  },
  "created_at": "2026-05-16T12:00:00"
}
```

Sales Turn：

```json
{
  "idx": 1,
  "speaker": "sales",
  "content": "如果主要是上课记笔记，我们先看两个点：书写体验和资料整理效率。你现在更担心预算，还是担心买了之后用不上？",
  "metadata": {
    "intent": "need_discovery",
    "used_product_context": true,
    "next_action": "clarify_budget_and_usage"
  },
  "created_at": "2026-05-16T12:00:10"
}
```

---

## 8.4 Session Memory 数据结构

```json
{
  "current_need": "用于课堂笔记和资料整理",
  "main_objections": ["价格高", "担心功能用不上"],
  "budget_boundary": "2500 左右",
  "emotional_state": "谨慎、防御、但有兴趣",
  "mentioned_competitors": [],
  "decision_constraints": ["预算有限"],
  "do_not_repeat": ["不要直接推荐高配版本"],
  "next_best_action": "继续确认学习场景，并解释功能是否匹配预算"
}
```

---

## 8.5 Judge Feedback 数据结构

```json
{
  "should_continue": true,
  "current_stage": "核心异议出现",
  "next_stage": "销冠挖掘动机",
  "dialogue_quality_score": 7.5,
  "sales_score": {
    "responsiveness": 8,
    "specificity": 7,
    "evidence_usage": 6,
    "objection_handling": 7,
    "closing_progress": 5
  },
  "persona_instruction": "继续围绕价格和竞品施压，不要轻易接受销售解释。",
  "sales_instruction": "下一轮必须先回应价格差异，再追问用户最核心的使用场景。",
  "avoid_repeating": ["不要重复长期价值更高这个笼统表达"],
  "end_status": "CONTINUE",
  "reason": "价格异议尚未被充分解决。"
}
```

---

## 8.6 Coach Review 数据结构

```json
{
  "outcome": "follow_up",
  "summary": "价格敏感学生对产品有兴趣，但由于预算压力和竞品对比，最终进入待跟进状态。",
  "user_profile_summary": {
    "main_need": "学习笔记和资料整理",
    "main_objections": ["价格高", "竞品更便宜", "担心功能用不上"],
    "budget_boundary": "2500 左右",
    "attitude_change": "从谨慎到部分认可，但未成交"
  },
  "main_objections": [],
  "effective_responses": [],
  "failed_responses": [],
  "script_candidates": {
    "one_sentence_pitch": "...",
    "three_key_selling_points": [],
    "objection_handling": [],
    "faq": [],
    "closing_script": "..."
  },
  "training_insights": [],
  "candidate_lessons": []
}
```

---

# 9. Agent 功能需求

## 9.1 Persona Agent

### 功能描述

根据 Persona YAML、当前阶段、Judge 指令、最近对话，生成真实用户发言。

### 输入

```text
persona_profile
pressure_profile
topic
current_stage
judge_feedback.persona_instruction
recent_history
session_memory
```

### 输出

```json
{
  "content": "用户发言",
  "hidden_state": {
    "intent": "price_objection",
    "attitude": "skeptical",
    "purchase_signal": 0.35,
    "status": "CONTINUE"
  }
}
```

### 业务规则

1. 不能自称 AI。
2. 不能主动帮助销售完成任务。
3. 不能前几轮无条件成交。
4. 必须符合压力参数。
5. 必须回应销售上一轮内容。
6. 如果销售没解决异议，应继续追问。
7. 如果耐心低且销售重复，应表现不耐烦。
8. 每轮发言不超过 150 字。

### 验收标准

1. 前 5 轮不会轻易成交。
2. 能提出符合人设的异议。
3. 能根据销冠回应改变态度。
4. 能输出合法 JSON。

---

## 9.2 Sales Champion Agent

### 功能描述

根据产品资料、当前会话画像、Judge 指令和最近对话，生成销冠回应。

### 输入

```text
topic
product_text 或 product_context
current_stage
session_memory
judge_feedback.sales_instruction
recent_history
```

### 输出

```json
{
  "content": "销冠回应",
  "strategy": {
    "intent": "price_reframing",
    "used_product_context": true,
    "next_action": "ask_usage_priority"
  }
}
```

### 业务规则

1. 必须先回应用户上一轮具体问题。
2. 不能编造产品事实。
3. 不要泛泛讲卖点。
4. 每轮最多讲 1-2 个重点。
5. 必须避免 Judge 提醒不要重复的表达。
6. 必须避免 Session Memory 中的 do_not_repeat。
7. 必要时追问。
8. 合适时推进下一步。
9. 每轮不超过 220 字。

### 验收标准

1. 对价格异议有具体回应。
2. 对竞品异议有对比思路。
3. 不重复用户已拒绝建议。
4. 能输出合法 JSON。

---

## 9.3 Judge Agent

### 功能描述

每隔固定轮次评估对话质量，控制阶段推进，并输出下一步指令。

### 调用时机

默认每 3 轮调用一次。

可配置：

```text
judge_interval = 3
```

### 输入

```text
topic
current_stage
round_idx
max_rounds
persona_profile
session_memory
recent_history
```

### 输出

Judge Feedback JSON。

### 业务规则

1. 判断是否跑题。
2. 判断是否重复。
3. 判断销冠是否回应具体异议。
4. 判断用户是否被过早说服。
5. 判断是否进入下一阶段。
6. 判断是否提高用户压力。
7. 判断是否结束。

### 验收标准

1. 能输出 current_stage 和 next_stage。
2. 能输出 persona_instruction。
3. 能输出 sales_instruction。
4. 能指出 avoid_repeating。
5. 能判断 end_status。

---

## 9.4 Session Memory 更新器

### 功能描述

每隔固定轮次，根据最近对话更新当前用户画像。

### 调用时机

默认每 3 轮调用一次。

可配置：

```text
memory_interval = 3
```

### 输入

```text
old_session_memory
recent_history
```

### 输出

Session Memory JSON。

### 业务规则

1. 记录用户当前需求。
2. 记录主要异议。
3. 记录预算边界。
4. 记录竞品。
5. 记录决策限制。
6. 记录不要重复的建议。
7. 给出下一步最佳动作。

### 验收标准

1. 能正确提取用户预算。
2. 能正确提取用户异议。
3. 能生成 do_not_repeat。
4. 能输出合法 JSON。

---

## 9.5 Coach Agent

### 功能描述

会话结束后，对完整对话进行复盘，并输出结构化业务资产。

### 输入

```text
persona_profile
product_summary
full_history
outcome
```

### 输出

Coach Review JSON。

### 业务规则

1. 不做泛泛评价。
2. 必须提取主要异议。
3. 必须区分有效回应和失败回应。
4. 必须生成更优说法。
5. 必须生成话术候选。
6. 必须生成培训洞察。
7. 必须生成候选经验。

### 验收标准

1. review.json 字段完整。
2. 至少输出 3 条 main_objections。
3. 至少输出 2 条 effective_responses。
4. 至少输出 2 条 failed_responses 或改进建议。
5. 至少输出 5 条 script_candidates。
6. 至少输出 3 条 training_insights。

---

# 10. 阶段驱动设计

## 10.1 默认阶段

```text
stage_1_opening: 开场与需求暴露
stage_2_objection: 核心异议出现
stage_3_discovery: 销冠挖掘动机
stage_4_matching: 方案匹配与价值锚定
stage_5_pressure_test: 强压测试
stage_6_closing: 成交推进或失败退出
```

## 10.2 阶段推进规则

MVP 可采用混合方式：

1. 基于轮次默认推进。
2. Judge Agent 可以覆盖阶段。

推荐默认：

| 轮次 | 阶段 |
|---|---|
| 1-3 | 开场与需求暴露 |
| 4-7 | 核心异议出现 |
| 8-11 | 销冠挖掘动机 |
| 12-15 | 方案匹配与价值锚定 |
| 16-18 | 强压测试 |
| 19-20 | 成交推进或失败退出 |

若 max_rounds 为 30，可等比例扩展。

## 10.3 阶段行为要求

### 开场与需求暴露

Persona：表达初始兴趣、预算、场景。  
Sales：追问需求，不急着成交。

### 核心异议出现

Persona：提出价格、竞品、信任等异议。  
Sales：必须具体回应。

### 销冠挖掘动机

Persona：暴露更真实动机。  
Sales：追问使用场景、决策标准、隐性需求。

### 方案匹配与价值锚定

Persona：比较是否适合自己。  
Sales：用产品信息匹配痛点。

### 强压测试

Persona：砍价、质疑、离场威胁。  
Sales：处理高压异议。

### 成交推进或失败退出

Persona：给出购买信号、待跟进或离开。  
Sales：推进下一步。

---

# 11. 输入输出设计

## 11.1 输入文件

### product.md

示例结构：

```markdown
# 产品名称

## 产品定位

## 核心卖点

## 价格信息

## 目标用户

## 售后政策

## 与竞品对比

## FAQ
```

### persona.yaml

见第 8.1 节。

### .env

```env
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
TEMPERATURE=0.7
```

---

## 11.2 输出目录

每次运行生成一个 session 目录：

```text
outputs/
└── session_20260516_153000_price_sensitive_student/
    ├── dialogue.json
    ├── review.json
    ├── script_candidates.md
    ├── session_memory.json
    ├── judge_feedback.json
    └── run.log
```

---

## 11.3 dialogue.json

```json
{
  "session_id": "session_20260516_153000_price_sensitive_student",
  "topic": "学习平板销售模拟",
  "persona_id": "price_sensitive_student",
  "max_rounds": 20,
  "outcome": "follow_up",
  "turns": [
    {
      "idx": 1,
      "speaker": "persona",
      "content": "...",
      "metadata": {}
    },
    {
      "idx": 1,
      "speaker": "sales",
      "content": "...",
      "metadata": {}
    }
  ]
}
```

---

## 11.4 review.json

见第 8.6 节。

---

## 11.5 script_candidates.md

```markdown
# 本场对话话术候选

## 1. 一句话推荐话术

## 2. 三大卖点标准话术

## 3. 用户异议处理话术

### 异议：价格太高

推荐回应：

错误回应：

## 4. FAQ 候选

## 5. 成交推进话术

## 6. 培训洞察

## 7. 禁用表达清单
```

---

# 12. 非功能需求

## 12.1 稳定性

1. 单场 20 轮对话必须能完整跑完。
2. 某次 LLM JSON 解析失败时，应自动重试一次。
3. 重试失败时，保存原始文本并继续或安全退出。
4. 所有输出必须落盘，避免中途失败后数据消失。

## 12.2 可观测性

控制台每轮输出：

```text
[Round 1] Persona speaking...
[Round 1] Sales speaking...
[Round 3] Updating session memory...
[Round 3] Judge checking...
```

不得只显示一个安静的黑框，让开发者怀疑自己是不是在看电子坟墓。

## 12.3 成本控制

1. Judge 默认每 3 轮调用一次。
2. Session Memory 默认每 3 轮调用一次。
3. Coach 只在会后调用一次。
4. 最近对话只传最近 6-10 条。
5. 长上下文通过 session_memory 压缩。

## 12.4 可配置性

必须支持配置：

```text
model_name
temperature
max_rounds
judge_interval
memory_interval
persona_path
product_path
output_dir
```

---

# 13. 异常处理需求

## 13.1 JSON 解析失败

处理逻辑：

1. 尝试从模型输出中提取 JSON。
2. 如果失败，调用 repair_json 函数。
3. 如果仍失败，用 fallback 结构保存原始文本。
4. 不要直接崩溃。

## 13.2 API 调用失败

处理逻辑：

1. 重试 2 次。
2. 每次等待 2 秒。
3. 仍失败则记录错误并结束当前 session。
4. 已生成内容必须保存。

## 13.3 Persona 文件缺字段

处理逻辑：

1. 启动时校验 YAML。
2. 缺少必填字段则报错。
3. 给出缺失字段列表。

## 13.4 产品资料为空

处理逻辑：

1. 启动时报错。
2. 提示检查 product.md。

---

# 14. 验收测试用例

## 14.1 单场基础测试

### 输入

```text
product.md：学习平板产品资料
persona：price_sensitive_student.yaml
max_rounds：20
```

### 预期输出

1. 生成完整 session 文件夹。
2. dialogue.json 不为空。
3. review.json 字段完整。
4. script_candidates.md 包含 5 个以上话术候选。

---

## 14.2 人设压力测试

### 输入

```text
persona：skeptical_parent.yaml
```

### 预期行为

1. 用户持续关注售后、孩子沉迷、学习效果。
2. 不会轻易成交。
3. Sales Agent 必须回应信任和安全问题。

---

## 14.3 Judge 控制测试

### 预期行为

1. 第 3 轮左右输出 Judge Feedback。
2. Feedback 包含 avoid_repeating。
3. 能推动阶段变化。
4. 能给 Persona 和 Sales 下一步指令。

---

## 14.4 Session Memory 测试

### 预期行为

1. 用户提过预算后，session_memory 记录预算。
2. 用户拒绝分期后，do_not_repeat 包含不要继续建议分期。
3. Sales Agent 后续不再重复建议分期。

---

## 14.5 Coach 复盘测试

### 预期行为

1. 能提取主要异议。
2. 能提取有效回应。
3. 能指出失败回应和更优话术。
4. 能生成 training_insights。
5. 能生成 candidate_lessons。

---

# 15. 开发里程碑

## 15.1 Milestone 1：项目骨架

目标：能运行空项目，加载配置和输入文件。

交付：

1. requirements.txt
2. .env.example
3. 目录结构
4. config.py
5. loaders.py
6. README 初版

验收：

```bash
python -m src.runner --help
```

能显示参数说明。

---

## 15.2 Milestone 2：Agent 基础调用

目标：Persona 和 Sales 能各生成一轮发言。

交付：

1. llm.py
2. agents.py
3. persona_prompt.md
4. sales_prompt.md

验收：

运行后能输出：

```text
Persona: ...
Sales: ...
```

---

## 15.3 Milestone 3：多轮循环

目标：跑满 max_rounds。

交付：

1. runner.py 主循环
2. DialogueState
3. recent_history / full_history

验收：

能生成 20 轮对话。

---

## 15.4 Milestone 4：Session Memory

目标：每 3 轮更新当前会话画像。

交付：

1. memory.py
2. session_memory_prompt.md
3. session_memory.json 输出

验收：

能提取预算、异议、do_not_repeat。

---

## 15.5 Milestone 5：Judge Agent

目标：每 3 轮进行对话质量判断。

交付：

1. judge.py
2. judge_prompt.md
3. judge_feedback.json 输出

验收：

能输出阶段、下一步指令和 end_status。

---

## 15.6 Milestone 6：Coach Agent

目标：会后生成结构化复盘。

交付：

1. coach.py
2. coach_prompt.md
3. review.json

验收：

review.json 字段完整，包含异议、有效回应、失败回应、话术候选。

---

## 15.7 Milestone 7：输出整理

目标：生成最终可读文件。

交付：

1. dialogue.json
2. review.json
3. script_candidates.md
4. lessons_candidate.jsonl

验收：

输出文件可直接打开阅读。

---

# 16. MVP 最终验收清单

```text
[ ] 项目可通过命令行启动
[ ] 可读取 product.md
[ ] 可读取 persona.yaml
[ ] 可生成 Persona 发言
[ ] 可生成 Sales 发言
[ ] 可运行 20 轮以上对话
[ ] 可阶段推进
[ ] 可更新 Session Memory
[ ] 可调用 Judge Agent
[ ] 可提前结束或正常结束
[ ] 可调用 Coach Agent
[ ] 可输出 dialogue.json
[ ] 可输出 review.json
[ ] 可输出 script_candidates.md
[ ] 可写入 lessons_candidate.jsonl
[ ] JSON 解析失败有兜底
[ ] API 失败有重试
[ ] README 有运行说明
```

---

# 17. MVP 之后的扩展方向

## 17.1 第二阶段：基础 RAG

加入产品资料切片、embedding、向量库召回，让 Sales Agent 更准确地引用产品信息。

## 17.2 第三阶段：经验库闭环

将 candidate_lessons 经过人工审核进入 approved_lessons，让 Sales Agent 可召回历史经验。

## 17.3 第四阶段：批量运行

多个 Persona 批量模拟，形成异议库和话术库。

## 17.4 第五阶段：Web 看板

开发 FastAPI + Vue3 看板，实现人设管理、会话查看、经验审核、统计分析。

## 17.5 第六阶段：Training Guide 流水线

把输出结果接入话术生成 Agent 和最终 Training Guide 整合 Agent。

---

# 18. PRD 总结

本 MVP 的核心不是炫技，而是验证一个关键命题：

```text
多 Agent 博弈能否稳定产出可复用销售资产？
```

因此第一版必须聚焦：

```text
四 Agent
阶段驱动
当前会话画像
结构化复盘
话术候选输出
```

只要第一版能稳定产出高质量对话、有效异议、失败示范和可复用话术，就已经证明这个系统值得继续扩展。至于 Web 看板、数据库、统计大屏，可以等发动机能转之后再装上去。否则不过是在给一堆未验证代码举办乔迁仪式。

