# 多人设销冠压力测试引擎 MVP / Vibe Coding 开发文档

版本：v0.1  
文档类型：Cursor / Vibe Coding 开发执行手册  
适用对象：使用 Cursor、Claude、GPT、DeepSeek 等 AI 编程助手进行本地快速开发  
目标：按阶段把 MVP 从 0 开发到可运行测试版  
开发方式：每个阶段都有明确目标、开发范围、验收标准和可直接复制给 AI 编程助手的提示词。

---

# 0. 开发总目标

本开发文档的目标是指导你通过 Cursor / vibe coding 快速开发一个本地 MVP：

```text
输入：product.md + persona.yaml + topic + max_rounds
运行：四 Agent 多轮销售模拟
输出：dialogue.json + review.json + script_candidates.md + lessons_candidate.jsonl
```

MVP 核心能力：

```text
Persona Agent：真实用户人设
Sales Champion Agent：销冠回应
Judge Agent：会中控制
Session Memory：当前会话画像
Coach Agent：会后复盘与资产提取
```

第一版不做 Web、不做数据库、不做正式 RAG、不做经验库 UI。别把一只还没学会走路的小狗送去参加敏捷犬大赛。

---

# 1. 开发阶段总览

MVP 建议分为 8 个开发阶段：

```text
阶段 1：项目骨架与基础配置
阶段 2：输入文件与数据结构
阶段 3：LLM 调用与 JSON 修复工具
阶段 4：Persona Agent 与 Sales Agent 单轮跑通
阶段 5：多轮对话 Runner
阶段 6：Session Memory 与 Judge Agent
阶段 7：Coach Agent 与输出文件
阶段 8：测试、调参、README 与第一版验收
```

每个阶段都应该单独提交一次代码。不要一次性让 AI 写完整项目。那通常会生成一座“看似完整、运行时报错”的软件鬼屋。

---

# 2. 技术选型

## 2.1 MVP 技术栈

```text
语言：Python 3.10+
模型调用：OpenAI 兼容 SDK
模型：DeepSeek Chat / GPT / 其他 OpenAI-compatible 模型
配置：python-dotenv
YAML：PyYAML
输出：JSON / Markdown / JSONL
测试：pytest 可选
```

## 2.2 暂不使用

```text
LangGraph：MVP 第一版可先不用，避免过早复杂化
Chroma：MVP 第一版可先不用，用完整 product.md 或简单截断
FastAPI：暂不做
Vue：暂不做
SQLite：暂不做
WebSocket：暂不做
```

后续再逐步替换。先写清楚业务逻辑，再让框架入场，不然框架会像热心亲戚一样占满你的客厅。

---

# 3. 推荐目录结构

```text
sales_game_mvp/
├── .env
├── .env.example
├── requirements.txt
├── README.md
├── data/
│   ├── product.md
│   ├── lessons_candidate.jsonl
│   └── sessions/
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
│   ├── schema.py
│   ├── llm.py
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

# 4. 全局开发约束

所有阶段都要遵守：

1. 每个模块职责单一。
2. 所有 LLM 输出都尽量要求 JSON。
3. 所有 JSON 解析必须有兜底。
4. 每轮对话必须实时写入内存状态。
5. 每次运行必须生成独立 session 目录。
6. 不要把 prompt 硬编码在 Python 文件里，放到 prompts 目录。
7. 不要先做 UI。
8. 不要引入过多框架。
9. 每个阶段完成后都能独立运行或测试。
10. 代码要可读，不要让 AI 写出一团“能跑但没人敢碰”的意大利面。

---

# 5. 阶段 1：项目骨架与基础配置

## 5.1 阶段目标

创建项目基础目录、依赖文件、配置文件和最小可运行入口。

## 5.2 本阶段要做什么

1. 创建目录结构。
2. 创建 requirements.txt。
3. 创建 .env.example。
4. 创建 src/config.py。
5. 创建 src/runner.py 的基础 CLI。
6. 创建 README.md 初版。

## 5.3 requirements.txt 建议

```txt
openai>=1.0.0
python-dotenv>=1.0.0
PyYAML>=6.0.0
pydantic>=2.0.0
rich>=13.0.0
```

## 5.4 .env.example

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
TEMPERATURE=0.7
MAX_RETRIES=2
```

## 5.5 Cursor 提示词

把下面这段直接发给 Cursor：

```text
你是一个资深 Python 工程师。请帮我创建一个名为 sales_game_mvp 的 Python MVP 项目骨架。

项目目标：开发一个本地运行的多人设销冠压力测试引擎。第一阶段只创建项目骨架和基础配置，不要实现 Agent 逻辑。

请创建以下目录和文件：

sales_game_mvp/
├── .env.example
├── requirements.txt
├── README.md
├── data/
│   ├── product.md
│   ├── lessons_candidate.jsonl
│   └── sessions/
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
│   ├── schema.py
│   ├── llm.py
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

要求：
1. requirements.txt 包含 openai、python-dotenv、PyYAML、pydantic、rich。
2. .env.example 包含 OPENAI_API_KEY、OPENAI_BASE_URL、MODEL_NAME、TEMPERATURE、MAX_RETRIES。
3. src/config.py 实现 load_settings()，从 .env 读取配置。
4. src/runner.py 实现 argparse，支持参数：--product、--persona、--topic、--max-rounds、--judge-interval、--memory-interval。
5. runner.py 暂时只打印读取到的参数和配置，不实现 Agent。
6. README.md 写明安装、配置、运行命令。
7. 代码要简洁、可维护、带基础异常处理。
```

## 5.6 阶段验收

运行：

```bash
pip install -r requirements.txt
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 20
```

预期：

```text
Settings loaded successfully
Product path: data/product.md
Persona path: personas/price_sensitive_student.yaml
Topic: 学习平板销售模拟
Max rounds: 20
```

---

# 6. 阶段 2：输入文件与数据结构

## 6.1 阶段目标

实现 product.md、persona.yaml 的读取和校验，定义核心数据结构。

## 6.2 本阶段要做什么

1. 编写 data/product.md 示例。
2. 编写 3 个 persona.yaml 示例。
3. 实现 loaders.py。
4. 实现 schema.py。
5. 在 runner.py 中加载 product 和 persona。

## 6.3 product.md 示例

```markdown
# 智学 Pro 学习平板

## 产品定位
智学 Pro 是一款面向学生和轻办公人群的学习平板，主打课堂笔记、资料整理、多任务学习和家长管控。

## 核心卖点
1. 低延迟手写体验，适合课堂笔记。
2. 多窗口学习模式，方便边看资料边做笔记。
3. AI 资料整理功能，可以自动归类学习资料。
4. 家长管控模式，限制娱乐应用使用时长。
5. 官方两年质保。

## 价格信息
标准版：2999 元。
高配版：3699 元。

## 目标用户
大学生、中学生家长、轻办公用户。

## 售后政策
支持 7 天无理由退货，官方两年质保。

## 竞品对比
竞品 A 价格更低，但手写延迟更高，不支持 AI 资料整理。
竞品 B 性能更强，但价格更高，家长管控较弱。

## FAQ
Q：为什么比竞品 A 贵？
A：主要差异在手写体验、多窗口学习、AI 资料整理和售后保障。
```

## 6.4 Persona 示例 1：价格敏感学生

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

## 6.5 Persona 示例 2：多疑家长

```yaml
id: skeptical_parent
name: 多疑家长
age: 42
occupation: 家长
budget: 3500
personality: 谨慎、多疑、重视孩子学习效果
pain_points:
  - 担心孩子沉迷娱乐
  - 担心买了之后学习效果不明显
  - 重视售后和质量
objection_style: 会连续追问证据、售后、真实效果和使用限制
purchase_goal: 给孩子买一个真正能帮助学习且不会沉迷的设备
pressure_profile:
  price_sensitivity: 0.6
  trust_threshold: 0.9
  patience: 0.5
  competitor_awareness: 0.6
  decision_power: 0.8
  emotion_volatility: 0.5
  need_urgency: 0.6
  skepticism: 0.95
  bargaining_aggressiveness: 0.5
```

## 6.6 Persona 示例 3：技术发烧友

```yaml
id: tech_enthusiast
name: 技术发烧友
age: 28
occupation: 产品经理
budget: 5000
personality: 理性、懂参数、关注性能和体验细节
pain_points:
  - 想买一台兼顾学习和轻办公的设备
  - 对参数和体验要求高
  - 不喜欢销售空话
objection_style: 会追问参数、性能、系统体验和竞品差异
purchase_goal: 买到体验和性能都足够优秀的设备
pressure_profile:
  price_sensitivity: 0.4
  trust_threshold: 0.8
  patience: 0.6
  competitor_awareness: 0.9
  decision_power: 0.9
  emotion_volatility: 0.3
  need_urgency: 0.5
  skepticism: 0.75
  bargaining_aggressiveness: 0.4
```

## 6.7 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 2：输入文件与数据结构。

请完成以下任务：

1. 在 data/product.md 中写入一个学习平板产品示例，包含产品定位、核心卖点、价格信息、目标用户、售后政策、竞品对比、FAQ。
2. 在 personas/ 下创建三个 YAML 人设：
   - price_sensitive_student.yaml
   - skeptical_parent.yaml
   - tech_enthusiast.yaml
3. 在 src/schema.py 中用 Pydantic 定义以下模型：
   - PressureProfile
   - PersonaProfile
   - Turn
   - SessionMemory
   - JudgeFeedback
   - CoachReview
   - DialogueState
4. 在 src/loaders.py 中实现：
   - load_text_file(path: str) -> str
   - load_persona_yaml(path: str) -> PersonaProfile
   - validate_product_text(text: str) -> None
5. 修改 src/runner.py：
   - 读取 product.md
   - 读取 persona.yaml
   - 打印产品字数、人设名称、人设压力参数
6. 要求：
   - YAML 缺字段时报清楚错误
   - product.md 为空时报错
   - 所有路径不存在时给出友好提示
   - 保持代码简洁

暂时不要实现 LLM 调用。
```

## 6.8 阶段验收

运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 20
```

预期：

```text
Product loaded: 约 xxx characters
Persona loaded: 价格敏感学生
Pressure profile: price_sensitivity=0.9, skepticism=0.8...
```

---

# 7. 阶段 3：LLM 调用与 JSON 修复工具

## 7.1 阶段目标

实现统一 LLM 调用层，支持 OpenAI 兼容接口，并提供 JSON 解析和修复工具。

## 7.2 本阶段要做什么

1. 实现 src/llm.py。
2. 实现 call_llm()。
3. 实现 call_llm_json()。
4. 实现 utils.py 中的 extract_json()。
5. 增加重试机制。
6. 增加基础日志。

## 7.3 llm.py 设计

核心函数：

```python
def call_llm(system_prompt: str, user_prompt: str, temperature: float | None = None) -> str:
    ...


def call_llm_json(system_prompt: str, user_prompt: str, temperature: float | None = None) -> dict:
    ...
```

## 7.4 JSON 解析策略

```text
1. 先直接 json.loads。
2. 如果失败，从文本中提取第一个 {...} JSON 块。
3. 如果仍失败，尝试清理 markdown code fence。
4. 如果仍失败，抛出可读错误或返回 fallback。
```

## 7.5 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 3：LLM 调用与 JSON 修复工具。

请完成以下任务：

1. 在 src/llm.py 中实现 OpenAI 兼容 SDK 调用。
   - 从 config.load_settings() 读取 api_key、base_url、model_name、temperature、max_retries。
   - 使用 openai.OpenAI client。
   - 实现 call_llm(system_prompt, user_prompt, temperature=None) -> str。
   - 实现 call_llm_json(system_prompt, user_prompt, temperature=None) -> dict。

2. 在 src/utils.py 中实现：
   - extract_json(text: str) -> dict
   - strip_code_fence(text: str) -> str
   - safe_json_dumps(data) -> str
   - now_timestamp() -> str

3. call_llm_json 的逻辑：
   - 调用 call_llm 得到文本。
   - 使用 extract_json 解析。
   - 如果解析失败，重试一次，并在 user_prompt 末尾强调“请只输出合法 JSON”。
   - 如果仍失败，抛出 RuntimeError，并包含原始输出片段。

4. 加入 rich 控制台日志，显示当前调用的模型和重试次数。

5. 修改 runner.py，增加一个 --test-llm 参数。
   - 当传入 --test-llm 时，调用模型输出一个 JSON：{"ok": true, "message": "LLM connected"}

要求：
- 不要把 API Key 打印到控制台。
- 错误信息要可读。
- 代码要适合后续 Agent 复用。
```

## 7.6 阶段验收

运行：

```bash
python -m src.runner --test-llm
```

预期：

```json
{
  "ok": true,
  "message": "LLM connected"
}
```

---

# 8. 阶段 4：Persona Agent 与 Sales Agent 单轮跑通

## 8.1 阶段目标

实现 Persona Agent 和 Sales Agent，先跑通一问一答。

## 8.2 本阶段要做什么

1. 编写 persona_prompt.md。
2. 编写 sales_prompt.md。
3. 实现 agents.py。
4. 在 runner.py 中支持 --one-turn-test。

---

## 8.3 Persona Prompt

写入 prompts/persona_prompt.md：

```text
你正在扮演一个真实用户，而不是 AI 助手。

你的用户画像如下：
{persona_profile}

你的压力参数如下：
{pressure_profile}

当前销售话题：
{topic}

当前对话阶段：
{stage}

当前 Judge 给你的行为指令：
{persona_instruction}

当前会话画像：
{session_memory}

最近对话：
{recent_history}

你的行为规则：
1. 你必须像真实用户一样表达，不要配合销售完成任务。
2. 如果销售没有解决你的核心顾虑，你要继续追问或反驳。
3. 如果价格敏感度高，你要持续关注价格和竞品。
4. 如果信任阈值高，你要要求证据、案例或保障。
5. 如果耐心低，销售废话太多时你可以表现出不耐烦。
6. 只有在核心顾虑被充分解决时，才可以释放购买信号。
7. 每次发言不超过 150 字。
8. 不能自称 AI。

请只输出合法 JSON，格式如下：
{
  "content": "你的用户发言",
  "hidden_state": {
    "intent": "当前意图",
    "attitude": "当前态度",
    "purchase_signal": 0.0,
    "status": "CONTINUE"
  }
}

status 只能是：CONTINUE、DEAL_DONE、WALK_AWAY、FOLLOW_UP。
```

---

## 8.4 Sales Prompt

写入 prompts/sales_prompt.md：

```text
你是一个高水平销冠，不是客服，也不是产品说明书。

你的目标：
理解用户真实需求，解决关键异议，建立信任，并在合适时推进成交。

当前销售话题：
{topic}

当前对话阶段：
{stage}

产品资料：
{product_context}

当前用户画像记忆：
{session_memory}

Judge 给你的下一步指令：
{sales_instruction}

最近对话：
{recent_history}

行为规则：
1. 必须先回应用户上一轮的具体问题。
2. 不允许编造产品规格、价格、售后政策。
3. 每次只讲与用户当前顾虑相关的 1-2 个重点。
4. 不要重复用户已经拒绝过的建议。
5. 不要使用空泛表达，例如“品质更好”“体验更佳”，除非给出具体证据。
6. 必要时用追问挖掘需求。
7. 合适时推进下一步行动。
8. 每次发言不超过 220 字。

请只输出合法 JSON，格式如下：
{
  "content": "销冠发言",
  "strategy": {
    "intent": "本轮策略",
    "used_product_context": true,
    "next_action": "下一步动作"
  }
}
```

---

## 8.5 agents.py 设计

实现：

```python
def generate_persona_turn(state: DialogueState) -> dict:
    ...


def generate_sales_turn(state: DialogueState) -> dict:
    ...
```

## 8.6 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 4：Persona Agent 与 Sales Agent 单轮跑通。

请完成以下任务：

1. 在 prompts/persona_prompt.md 中写入 Persona Agent prompt。
2. 在 prompts/sales_prompt.md 中写入 Sales Champion Agent prompt。
3. 在 src/agents.py 中实现：
   - load_prompt(name: str) -> str
   - render_prompt(template: str, variables: dict) -> str
   - generate_persona_turn(state: DialogueState) -> dict
   - generate_sales_turn(state: DialogueState) -> dict
4. generate_persona_turn 要读取：
   - persona_profile
   - pressure_profile
   - topic
   - current_stage
   - judge_feedback.persona_instruction，如果没有则使用默认“按人设自然表达需求和顾虑”
   - session_memory
   - recent_history
5. generate_sales_turn 要读取：
   - topic
   - current_stage
   - product_text，第一版可直接截取前 5000 字作为 product_context
   - session_memory
   - judge_feedback.sales_instruction，如果没有则使用默认“回应用户并追问需求”
   - recent_history
6. 修改 runner.py，增加 --one-turn-test 参数。
   - 加载 product 和 persona。
   - 初始化 DialogueState。
   - 调用 generate_persona_turn。
   - 把 Persona turn 放入 history。
   - 调用 generate_sales_turn。
   - 打印两轮内容。
7. 所有 Agent 输出必须解析为 JSON，如果失败要报清楚错误。

要求：
- 不要实现多轮循环。
- 不要实现 Judge 和 Coach。
- 保持函数清晰，方便后续复用。
```

## 8.7 阶段验收

运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --one-turn-test
```

预期输出：

```text
Persona: 我主要想买来上课记笔记，但 2999 对我来说有点超预算了，你们和便宜一点的竞品差在哪？
Sales: 你担心预算很正常。先不急着看总价，我们可以看你每天最常用的两个场景：课堂笔记和资料整理...
```

---

# 9. 阶段 5：多轮对话 Runner

## 9.1 阶段目标

实现 20-50 轮循环对话，保存完整历史。

## 9.2 本阶段要做什么

1. 实现 run_session()。
2. 每轮执行 Persona → Sales。
3. 记录 full_history 和 recent_history。
4. 支持 max_rounds。
5. 根据 Persona status 初步判断结束。
6. 控制台输出每轮进度。

## 9.3 主循环伪代码

```python
for round_idx in range(1, max_rounds + 1):
    state.round_idx = round_idx
    state.current_stage = get_stage_by_round(round_idx, max_rounds)

    persona_turn = generate_persona_turn(state)
    append_turn(persona_turn)

    if persona_turn.hidden_state.status in ["DEAL_DONE", "WALK_AWAY", "FOLLOW_UP"]:
        state.outcome = persona_turn.hidden_state.status
        break

    sales_turn = generate_sales_turn(state)
    append_turn(sales_turn)

state.outcome = state.outcome or "TIMEOUT"
```

## 9.4 阶段函数

实现：

```python
def get_stage_by_round(round_idx: int, max_rounds: int) -> str:
    ...
```

推荐阶段：

```text
1. 开场与需求暴露
2. 核心异议出现
3. 销冠挖掘动机
4. 方案匹配与价值锚定
5. 强压测试
6. 成交推进或失败退出
```

## 9.5 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 5：多轮对话 Runner。

请完成以下任务：

1. 在 src/runner.py 或单独的 src/session.py 中实现 run_session()。
2. run_session 输入：
   - product_text
   - persona_profile
   - topic
   - max_rounds
   - judge_interval
   - memory_interval
3. 初始化 DialogueState，包含：
   - session_id
   - topic
   - product_text
   - persona_profile
   - round_idx
   - max_rounds
   - current_stage
   - outcome
   - recent_history
   - full_history
   - session_memory
   - judge_feedback
4. 实现 get_stage_by_round(round_idx, max_rounds)，将对话分为六个阶段：
   - 开场与需求暴露
   - 核心异议出现
   - 销冠挖掘动机
   - 方案匹配与价值锚定
   - 强压测试
   - 成交推进或失败退出
5. 主循环：
   - 每轮先调用 generate_persona_turn
   - 保存 persona turn
   - 如果 persona hidden_state.status 是 DEAL_DONE / WALK_AWAY / FOLLOW_UP，则结束
   - 再调用 generate_sales_turn
   - 保存 sales turn
   - 如果达到 max_rounds，则 outcome=TIMEOUT
6. recent_history 只保留最近 10 条，full_history 保存全部。
7. 控制台用 rich 打印每轮 speaker 和 content。
8. 暂时不要加入 Judge、Memory、Coach。
9. 修改 runner.py，让普通运行命令可以跑完整多轮对话。

要求：
- 每个 turn 结构统一。
- 即使中途异常，也尽量保留已生成 history。
- 代码要清晰，方便下一阶段插入 Judge 和 Memory。
```

## 9.6 阶段验收

运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 10
```

预期：

```text
Round 1 / 10 - 开场与需求暴露
Persona: ...
Sales: ...

Round 2 / 10 - 开场与需求暴露
Persona: ...
Sales: ...
...
Session ended: TIMEOUT
```

---

# 10. 阶段 6：Session Memory 与 Judge Agent

## 10.1 阶段目标

加入当前会话画像和会中裁判能力，提升对话质量。

## 10.2 本阶段要做什么

1. 编写 session_memory_prompt.md。
2. 编写 judge_prompt.md。
3. 实现 memory.py。
4. 实现 judge.py。
5. 在 run_session 中按 interval 调用。
6. 将 memory 和 judge 结果注入后续 Agent。

---

## 10.3 Session Memory Prompt

写入 prompts/session_memory_prompt.md：

```text
你是当前会话画像记忆更新器。

你的任务是根据最近对话，更新用户画像和销售注意事项，帮助销冠避免失忆、重复和误踩雷区。

旧会话画像：
{old_session_memory}

最近对话：
{recent_history}

请只输出合法 JSON，格式如下：
{
  "current_need": "用户当前需求",
  "main_objections": [],
  "budget_boundary": "预算边界",
  "emotional_state": "情绪状态",
  "mentioned_competitors": [],
  "decision_constraints": [],
  "do_not_repeat": [],
  "next_best_action": "下一步最佳动作"
}
```

---

## 10.4 Judge Prompt

写入 prompts/judge_prompt.md：

```text
你是多 Agent 销售模拟系统的会中裁判和对话导演。

你的任务：
判断当前对话质量，控制阶段推进，防止跑题、重复、假成交，并给下一轮用户和销冠明确指令。

当前话题：
{topic}

当前阶段：
{stage}

当前轮次：
{round_idx} / {max_rounds}

用户人设：
{persona_profile}

当前会话画像记忆：
{session_memory}

最近对话：
{recent_history}

请评估：
1. 用户核心异议是否已经出现？
2. 销冠是否具体回应？
3. 是否出现重复表达？
4. 是否存在假成交风险？
5. 是否应该进入下一阶段？
6. 是否应该提高用户压力？
7. 是否应该结束？

请只输出合法 JSON，格式如下：
{
  "should_continue": true,
  "current_stage": "当前阶段",
  "next_stage": "下一阶段",
  "dialogue_quality_score": 0,
  "sales_score": {
    "responsiveness": 0,
    "specificity": 0,
    "evidence_usage": 0,
    "objection_handling": 0,
    "closing_progress": 0
  },
  "persona_instruction": "下一轮用户该如何表现",
  "sales_instruction": "下一轮销冠该如何回应",
  "avoid_repeating": [],
  "end_status": "CONTINUE",
  "reason": "判断理由"
}

end_status 只能是：CONTINUE、DEAL_DONE、WALK_AWAY、FOLLOW_UP、TIMEOUT。
```

---

## 10.5 memory.py 设计

实现：

```python
def update_session_memory(state: DialogueState) -> dict:
    ...
```

## 10.6 judge.py 设计

实现：

```python
def judge_dialogue(state: DialogueState) -> dict:
    ...
```

## 10.7 Runner 插入逻辑

推荐在每轮 Sales 之后判断：

```python
if round_idx % memory_interval == 0:
    state.session_memory = update_session_memory(state)

if round_idx % judge_interval == 0:
    state.judge_feedback = judge_dialogue(state)
    state.current_stage = state.judge_feedback.get("next_stage", state.current_stage)
    if state.judge_feedback.get("end_status") != "CONTINUE":
        state.outcome = state.judge_feedback["end_status"]
        break
```

## 10.8 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 6：Session Memory 与 Judge Agent。

请完成以下任务：

1. 在 prompts/session_memory_prompt.md 中写入当前会话画像更新 prompt。
2. 在 prompts/judge_prompt.md 中写入 Judge Agent prompt。
3. 在 src/memory.py 中实现 update_session_memory(state: DialogueState) -> dict。
   - 读取 old_session_memory 和 recent_history。
   - 调用 call_llm_json。
   - 返回 Session Memory dict。
4. 在 src/judge.py 中实现 judge_dialogue(state: DialogueState) -> dict。
   - 读取 topic、current_stage、round_idx、max_rounds、persona_profile、session_memory、recent_history。
   - 调用 call_llm_json。
   - 返回 Judge Feedback dict。
5. 修改 run_session 主循环：
   - 每 memory_interval 轮调用 update_session_memory。
   - 每 judge_interval 轮调用 judge_dialogue。
   - Judge 输出后更新 state.judge_feedback。
   - 如果 Judge 的 end_status 不是 CONTINUE，则结束会话。
   - 如果 Judge 有 next_stage，则更新 current_stage。
6. 修改 generate_persona_turn 和 generate_sales_turn：
   - 确保它们能读取最新 judge_feedback 和 session_memory。
7. 控制台显示：
   - Updating session memory...
   - Judge checking...
   - Judge reason: xxx
8. 把每次 memory 和 judge 的输出暂存在 state 中。

要求：
- JSON 解析失败时不要让整个会话直接崩溃，可以记录错误并继续。
- Judge 不要每轮调用，只按 judge_interval 调用。
- Session Memory 只按 memory_interval 调用。
```

## 10.9 阶段验收

运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 12 --judge-interval 3 --memory-interval 3
```

预期：

```text
Round 3 complete
Updating session memory...
Session memory updated: main_objections=[...]
Judge checking...
Judge reason: 用户价格异议尚未解决，需要继续施压
```

---

# 11. 阶段 7：Coach Agent 与输出文件

## 11.1 阶段目标

会话结束后，调用 Coach Agent 生成结构化复盘，并输出文件。

## 11.2 本阶段要做什么

1. 编写 coach_prompt.md。
2. 实现 coach.py。
3. 实现 output.py。
4. 输出 dialogue.json。
5. 输出 review.json。
6. 输出 script_candidates.md。
7. 写入 lessons_candidate.jsonl。

---

## 11.3 Coach Prompt

写入 prompts/coach_prompt.md：

```text
你是销售模拟会话的复盘教练和业务资产提取专家。

你的任务不是泛泛点评，而是把整场对话转化为可复用销售资产和培训资产。

用户人设：
{persona_profile}

产品信息摘要：
{product_summary}

完整对话：
{dialogue}

最终结果：
{outcome}

请只输出严格 JSON，格式如下：
{
  "outcome": "deal_done / walk_away / follow_up / timeout",
  "summary": "本场一句话总结",
  "user_profile_summary": {
    "main_need": "用户主要需求",
    "main_objections": [],
    "budget_boundary": "预算边界",
    "attitude_change": "态度变化"
  },
  "main_objections": [
    {
      "objection": "异议内容",
      "turn_idx": 0,
      "intensity": 0.0,
      "resolved": false,
      "reason": "是否解决及原因"
    }
  ],
  "effective_responses": [
    {
      "scene": "场景",
      "sales_reply": "销冠原话或摘要",
      "why_it_worked": "为什么有效",
      "can_reuse_as_script": true
    }
  ],
  "failed_responses": [
    {
      "scene": "场景",
      "sales_reply": "失败原话或摘要",
      "problem": "问题是什么",
      "better_reply": "更优说法"
    }
  ],
  "script_candidates": {
    "one_sentence_pitch": "一句话推荐话术",
    "three_key_selling_points": [],
    "objection_handling": [
      {
        "objection": "异议",
        "reply": "推荐回应"
      }
    ],
    "faq": [
      {
        "question": "问题",
        "answer": "回答"
      }
    ],
    "closing_script": "成交推进话术"
  },
  "training_insights": [],
  "candidate_lessons": [
    {
      "trigger": "触发情境",
      "strategy": "应对策略",
      "evidence_turn_idx": 0,
      "confidence": 0.0,
      "status": "candidate"
    }
  ]
}

要求：
1. 每个有效回应必须说明为什么有效。
2. 每个失败回应必须给出更优说法。
3. 话术候选要能直接进入培训材料。
4. 候选经验必须包含 trigger、strategy、evidence_turn_idx、confidence。
5. 不要输出 markdown，只输出 JSON。
```

---

## 11.4 coach.py 设计

实现：

```python
def run_coach_review(state: DialogueState) -> dict:
    ...
```

## 11.5 output.py 设计

实现：

```python
def create_session_output_dir(session_id: str, persona_id: str) -> Path:
    ...


def save_dialogue_json(state: DialogueState, output_dir: Path) -> None:
    ...


def save_review_json(review: dict, output_dir: Path) -> None:
    ...


def save_script_candidates_md(review: dict, output_dir: Path) -> None:
    ...


def append_candidate_lessons(review: dict, path: str = "data/lessons_candidate.jsonl") -> None:
    ...
```

## 11.6 script_candidates.md 格式

```markdown
# 本场对话话术候选

## 1. 一句话推荐话术

{one_sentence_pitch}

## 2. 三大卖点标准话术

- ...

## 3. 用户异议处理话术

### 异议：xxx

推荐回应：xxx

## 4. FAQ 候选

### Q：xxx

A：xxx

## 5. 成交推进话术

{closing_script}

## 6. 培训洞察

- ...

## 7. 候选经验

- 触发情境：xxx
  应对策略：xxx
```

## 11.7 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 7：Coach Agent 与输出文件。

请完成以下任务：

1. 在 prompts/coach_prompt.md 中写入 Coach Agent prompt。
2. 在 src/coach.py 中实现 run_coach_review(state: DialogueState) -> dict。
   - 输入 persona_profile、product_summary、full_history、outcome。
   - 调用 call_llm_json。
   - 返回结构化 review。
3. 在 src/output.py 中实现：
   - create_session_output_dir(session_id: str, persona_id: str) -> Path
   - save_dialogue_json(state, output_dir)
   - save_review_json(review, output_dir)
   - save_script_candidates_md(review, output_dir)
   - save_session_memory_json(state, output_dir)
   - save_judge_feedback_json(state, output_dir)
   - append_candidate_lessons(review, path="data/lessons_candidate.jsonl")
4. 修改 run_session：
   - 会话结束后调用 run_coach_review。
   - 将 coach_review 存入 state。
   - 调用 output.py 保存所有文件。
5. 输出目录格式：
   outputs/session_YYYYMMDD_HHMMSS_{persona_id}/
6. dialogue.json 包含：session_id、topic、persona_id、max_rounds、outcome、turns。
7. review.json 保存 Coach 原始 JSON。
8. script_candidates.md 生成可读 Markdown。
9. candidate_lessons 逐行追加到 data/lessons_candidate.jsonl，每行一个 JSON。

要求：
- 即使 Coach 调用失败，也要保存 dialogue.json。
- Markdown 输出要清晰，方便直接阅读。
- 不要加入 Web 或数据库。
```

## 11.8 阶段验收

运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 20
```

预期输出目录：

```text
outputs/session_20260516_153000_price_sensitive_student/
├── dialogue.json
├── review.json
├── script_candidates.md
├── session_memory.json
├── judge_feedback.json
└── run.log
```

---

# 12. 阶段 8：测试、调参、README 与第一版验收

## 12.1 阶段目标

修复第一版运行问题，补充 README，形成可复用测试流程。

## 12.2 本阶段要做什么

1. 增加基础测试脚本。
2. 增加 README 运行说明。
3. 增加常见错误说明。
4. 用三个 Persona 各跑一场。
5. 手动评估输出质量。
6. 调整 Prompt。

## 12.3 推荐测试命令

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 20

python -m src.runner --product data/product.md --persona personas/skeptical_parent.yaml --topic "学习平板销售模拟" --max-rounds 20

python -m src.runner --product data/product.md --persona personas/tech_enthusiast.yaml --topic "学习平板销售模拟" --max-rounds 20
```

## 12.4 输出质量检查表

每场对话检查：

```text
[ ] 用户是否符合人设？
[ ] 用户是否提出了至少 3 个异议？
[ ] 用户是否没有过早成交？
[ ] 销冠是否回应具体问题？
[ ] 销冠是否引用了产品资料？
[ ] 销冠是否出现重复废话？
[ ] Judge 是否给出有效指令？
[ ] Session Memory 是否记录了预算和异议？
[ ] Coach 是否提取了有效回应？
[ ] Coach 是否指出失败回应？
[ ] script_candidates.md 是否能直接用于培训？
```

## 12.5 Cursor 提示词

```text
继续开发 sales_game_mvp 项目。现在进入阶段 8：测试、调参、README 与第一版验收。

请完成以下任务：

1. 更新 README.md，包含：
   - 项目简介
   - 安装步骤
   - .env 配置方式
   - 单场运行命令
   - 三个人设测试命令
   - 输出文件说明
   - 常见错误排查
2. 在 README 中加入 MVP 验收标准。
3. 检查所有模块的 import 是否正确。
4. 检查 runner.py 是否支持：
   - --product
   - --persona
   - --topic
   - --max-rounds
   - --judge-interval
   - --memory-interval
   - --test-llm
   - --one-turn-test
5. 增加一个 scripts 或命令说明，用于依次运行三个 Persona。
6. 如果没有测试框架，也至少写一个 docs/manual_test_checklist.md，列出人工检查清单。
7. 清理无用代码和重复函数。
8. 确保任何情况下已生成对话都尽量保存。

要求：
- 不要添加新大功能。
- 只做收尾、稳定性和文档。
- README 要让一个新开发者能直接跑起来。
```

## 12.6 阶段验收

最终运行：

```bash
python -m src.runner --product data/product.md --persona personas/price_sensitive_student.yaml --topic "学习平板销售模拟" --max-rounds 20 --judge-interval 3 --memory-interval 3
```

验收成功条件：

```text
[ ] 运行不中断
[ ] 输出完整 session 目录
[ ] dialogue.json 有完整对话
[ ] review.json 字段完整
[ ] script_candidates.md 可读
[ ] lessons_candidate.jsonl 有候选经验
[ ] 控制台日志清晰
```

---

# 13. 每个阶段完成后的 Git 提交建议

```bash
git add .
git commit -m "stage 1: scaffold project structure"

git commit -m "stage 2: add loaders and schemas"

git commit -m "stage 3: add llm client and json parser"

git commit -m "stage 4: implement persona and sales agents"

git commit -m "stage 5: implement multi-turn session runner"

git commit -m "stage 6: add session memory and judge agent"

git commit -m "stage 7: add coach review and output files"

git commit -m "stage 8: polish docs and manual tests"
```

别等所有东西都写完再提交。那不是版本管理，那是把遗嘱写进代码仓库。

---

# 14. 推荐开发节奏

## 14.1 每阶段操作流程

```text
1. 复制当前阶段提示词给 Cursor。
2. 让 Cursor 修改代码。
3. 立即运行阶段验收命令。
4. 报错就把完整报错贴回 Cursor。
5. 跑通后手动检查关键文件。
6. git commit。
7. 进入下一阶段。
```

## 14.2 不建议的操作

```text
1. 不要一次性让 Cursor 生成所有阶段。
2. 不要边做 Web 边做 Agent。
3. 不要还没跑通单场就开始批量。
4. 不要还没校验输出质量就做数据库。
5. 不要把 prompt 全写死在 Python 文件里。
6. 不要忽略 JSON 解析失败。
7. 不要把模型输出当成永远靠谱。
```

模型输出永远靠谱这件事，和人类会议永远准时一样，属于文明幻想。

---

# 15. 关键调参建议

## 15.1 temperature

推荐：

```text
Persona Agent：0.8
Sales Agent：0.6
Judge Agent：0.2
Session Memory：0.2
Coach Agent：0.3
```

MVP 第一版如果不做分 Agent temperature，也可以统一 0.7。

## 15.2 max_rounds

测试阶段建议：

```text
快速调试：6
正常测试：20
深度模拟：30
```

## 15.3 judge_interval

推荐：

```text
3
```

太频繁成本高，太稀疏容易失控。

## 15.4 memory_interval

推荐：

```text
3
```

与 Judge 同步即可。

## 15.5 recent_history 长度

推荐：

```text
最近 10 条消息
```

更早信息交给 session_memory。

---

# 16. 常见问题与修复提示词

## 16.1 JSON 解析失败

给 Cursor 的修复提示词：

```text
当前项目中 LLM 输出经常 JSON 解析失败。请检查 src/llm.py 和 src/utils.py，增强 JSON 解析鲁棒性。

要求：
1. 支持解析 ```json ... ``` 代码块。
2. 支持从长文本中提取第一个完整 JSON object。
3. 如果字段缺失，尽量填充默认值。
4. call_llm_json 失败时自动重试一次，并追加“只输出 JSON，不要解释”。
5. 如果仍失败，返回 fallback dict，包含 raw_output 和 parse_error，而不是直接崩溃。
```

## 16.2 Persona 太容易成交

修复提示词：

```text
当前 Persona Agent 太容易被销售说服，导致模拟不真实。请优化 prompts/persona_prompt.md。

要求：
1. 强调用户不是来配合销售的。
2. 前 30% 轮次不得输出 DEAL_DONE，除非销售完美解决所有核心异议。
3. 根据 pressure_profile 提高质疑强度。
4. 如果 price_sensitivity 高，必须多次追问价格和竞品。
5. 如果 trust_threshold 高，必须要求证据、售后或案例。
6. 如果 Sales 回答空泛，Persona 应表现不满或继续追问。
```

## 16.3 Sales 回答太空泛

修复提示词：

```text
当前 Sales Agent 回答太空泛，经常说“品质更好”“长期价值更高”，缺少具体回应。请优化 prompts/sales_prompt.md。

要求：
1. 必须先引用用户上一轮的具体顾虑。
2. 每次回应必须包含一个具体产品信息或一个明确追问。
3. 禁止空泛表达，除非后面跟具体证据。
4. 面对价格异议，要先共情，再拆解价值。
5. 面对竞品异议，要承认对方优势，再做具体维度对比。
6. 面对信任异议，要提供售后、政策或证据。
```

## 16.4 Judge 没有实际作用

修复提示词：

```text
当前 Judge Agent 输出比较空泛，对后续对话影响不明显。请优化 prompts/judge_prompt.md 和 runner 中的注入逻辑。

要求：
1. Judge 必须输出具体 persona_instruction 和 sales_instruction。
2. Judge 必须输出 avoid_repeating。
3. 下一轮 Persona 和 Sales prompt 必须注入这些指令。
4. Judge 应明确指出当前最大问题。
5. Judge 应根据阶段决定是否提高用户压力。
6. 如果出现假成交风险，Judge 应要求 Persona 继续提出未解决异议。
```

## 16.5 Coach 输出没法复用

修复提示词：

```text
当前 Coach Agent 的复盘太泛，不能直接用于培训材料。请优化 prompts/coach_prompt.md。

要求：
1. 每条 effective_response 必须包含 scene、sales_reply、why_it_worked、can_reuse_as_script。
2. 每条 failed_response 必须包含 scene、sales_reply、problem、better_reply。
3. script_candidates 必须包含一句话话术、三大卖点、异议处理、FAQ、成交推进话术。
4. training_insights 必须写成培训材料能直接使用的表达。
5. candidate_lessons 必须是结构化经验，不要写空泛总结。
```

---

# 17. 第一版完成后的人工评估方法

## 17.1 单场评估

每场对话结束后打开：

```text
outputs/session_xxx/dialogue.json
outputs/session_xxx/review.json
outputs/session_xxx/script_candidates.md
```

人工判断：

1. 这场对话像不像真实销售？
2. 用户有没有明确人设？
3. 销冠有没有具体回应？
4. Judge 有没有让对话变难？
5. Coach 提炼的内容有没有业务价值？

## 17.2 三人设对比

分别运行：

```text
价格敏感学生
多疑家长
技术发烧友
```

观察三类输出是否有差异：

| 人设 | 预期核心异议 |
|---|---|
| 价格敏感学生 | 价格、竞品、优惠、性价比 |
| 多疑家长 | 沉迷、学习效果、售后、可信度 |
| 技术发烧友 | 参数、性能、系统体验、竞品差异 |

如果三个人设问出来的问题差不多，说明 Persona Prompt 或 pressure_profile 没起作用。

## 17.3 输出资产评估

重点看 script_candidates.md：

```text
[ ] 是否有一句话话术？
[ ] 是否有三大卖点？
[ ] 是否有针对异议的回应？
[ ] 是否有 FAQ？
[ ] 是否有成交推进话术？
[ ] 是否有禁用表达或错误示范？
[ ] 是否可以直接放进 Training Guide？
```

---

# 18. MVP 完成定义 Definition of Done

第一版 MVP 完成必须满足：

```text
[ ] 能通过命令行运行
[ ] 能读取产品资料
[ ] 能读取三类人设
[ ] 能运行 Persona + Sales 多轮对话
[ ] 能定期更新 Session Memory
[ ] 能定期调用 Judge
[ ] 能在会后调用 Coach
[ ] 能输出完整 session 目录
[ ] dialogue.json 可读
[ ] review.json 结构完整
[ ] script_candidates.md 有复用价值
[ ] lessons_candidate.jsonl 有候选经验
[ ] README 能指导新开发者跑起来
[ ] 至少完成三个人设的手动测试
```

---

# 19. MVP 到下一阶段的升级路线

## 19.1 升级到 LangGraph

当 runner.py 主循环稳定后，可以将流程迁移到 LangGraph：

```text
Persona Node
Sales Node
Memory Node
Judge Node
Coach Node
Output Node
```

## 19.2 加入产品知识 RAG

把 product.md 替换为：

```text
文档切片
Embedding
向量召回
Product KB hits
```

## 19.3 加入经验库

把 lessons_candidate.jsonl 升级为：

```text
candidate_lessons
approved_lessons
相似度去重
人工审核
召回使用
```

## 19.4 加入批量测试

实现：

```bash
python -m src.batch_runner --product data/product.md --personas personas/ --max-rounds 20
```

输出：

```text
多场 dialogue
汇总 review
异议排行
话术候选合并
```

## 19.5 加入 Web 看板

最后再做：

```text
FastAPI
Vue3
WebSocket
会话历史
经验库管理
统计看板
```

---

# 20. 开发文档总结

这个 MVP 的开发原则只有一句：

```text
先让四 Agent 引擎稳定产出高质量销售资产，再考虑平台化。
```

开发顺序必须克制：

```text
骨架
→ 输入与 schema
→ LLM 层
→ 双 Agent 单轮
→ 多轮循环
→ Memory + Judge
→ Coach + 输出
→ 测试和调参
```

每个阶段都有明确提示词，直接复制给 Cursor，一阶段一阶段推进。不要跳步，不要同时做五件事，不要在还没跑通对话时研究统计大屏。统计大屏本质上是给已经有数据的人看的，不是给幻想中的数据提前布置婚房。

