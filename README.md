# DealMind · 多人设销冠压力测试引擎

用不同用户人设对销冠 Agent 进行多轮博弈压力测试，自动复盘并沉淀销售经验。

---

## 系统概述

```
Persona Agent (用户人设)  ←→  Sales Agent (销冠)
         ↕                           ↕
    Session Memory              Judge Agent
    (实时画像更新)             (会中质量控制)
              ↓ 会话结束后
          Coach Agent (深度复盘)
              ↓
    4 个结构化输出文件
```

**核心能力：**
- 多人设压力测试：预算敏感、极度怀疑型、技术发烧友等不同用户
- 6 阶段销售路径自动推进（开场 → 核心异议 → 挖掘动机 → 价值锚定 → 强压 → 成交/退出）
- Judge Agent 会中控制：评分、阶段推进、防假成交、给双方下一轮指令
- Session Memory 实时更新：do_not_repeat、主要异议、预算边界、情绪状态
- Coach Agent 深度复盘：有效/失效策略分析、更优话术模板、可复用策略模式
- 自动输出 4 个业务文件：完整日志、对话 JSONL、候选经验、Markdown 摘要

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY（DeepSeek Key）
```

`.env` 示例：
```
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
TEMPERATURE=0.7
MAX_RETRIES=2
```

### 3. 验证连通性

```bash
python -m src.runner --test-llm
```

### 4. 运行压力测试

```bash
# 使用预算敏感学生人设，跑 6 轮
python -m src.runner --persona personas/price_sensitive_student.yaml --max-rounds 6

# 使用怀疑型家长人设，跑 10 轮
python -m src.runner --persona personas/skeptical_parent.yaml --max-rounds 10

# 技术发烧友人设，调整 Judge 触发频率
python -m src.runner --persona personas/tech_enthusiast.yaml --max-rounds 8 --judge-interval 2
```

---

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--persona` | `personas/price_sensitive_student.yaml` | 人设 YAML 文件路径 |
| `--product` | `data/product.md` | 产品资料 Markdown 路径 |
| `--topic` | `学习平板销售模拟` | 会话主题 |
| `--max-rounds` | `20` | 最大对话轮数 |
| `--judge-interval` | `3` | 每隔几轮触发 Judge Agent |
| `--memory-interval` | `3` | 每隔几轮更新 Session Memory |
| `--output-dir` | `outputs` | 输出文件根目录 |
| `--test-llm` | — | 仅做 LLM 连通性测试后退出 |

---

## 输出文件

每次会话在 `outputs/{session_id}/` 下生成 4 个文件：

| 文件 | 内容 |
|------|------|
| `session_log.json` | 完整结构化会话记录（含 coach_review、judge_feedback、session_memory） |
| `dialogue.jsonl` | 每轮对话（每行一条 turn，含 stage、metadata） |
| `lessons_candidate.jsonl` | Coach 提炼的候选经验（key_lesson / reusable_tactic / rebuttal_template） |
| `summary.md` | 人类可读 Markdown 摘要（画像记忆 + Coach 复盘 + 话术模板） |

---

## 目录结构

```
f:\Dealmind\
├── src/
│   ├── __init__.py
│   ├── config.py          # 环境变量加载
│   ├── schema.py          # Pydantic 数据模型
│   ├── loaders.py         # 文件加载与校验
│   ├── utils.py           # JSON 解析工具
│   ├── llm.py             # LLM 调用封装（重试、JSON 解析）
│   ├── agents.py          # Persona / Sales Agent
│   ├── judge.py           # Judge Agent（会中裁判）
│   ├── memory.py          # Session Memory 更新器
│   ├── coach.py           # Coach Agent（会后复盘）
│   ├── session.py         # 多轮会话主循环
│   ├── output_writer.py   # 4 个输出文件写出
│   └── runner.py          # CLI 入口
├── prompts/
│   ├── persona_prompt.md        # Persona Agent 系统提示词
│   ├── sales_prompt.md          # Sales Agent 系统提示词
│   ├── judge_prompt.md          # Judge Agent 系统提示词
│   ├── session_memory_prompt.md # Session Memory 提取提示词
│   └── coach_prompt.md          # Coach Agent 复盘提示词
├── personas/
│   ├── price_sensitive_student.yaml   # 预算敏感学生（难度 8/10）
│   ├── skeptical_parent.yaml          # 极度怀疑型家长（难度 9/10）
│   └── tech_enthusiast.yaml           # 技术发烧友（难度 8/10）
├── data/
│   └── product.md         # 产品资料（智学 Pro 学习平板）
├── outputs/               # 会话输出（git 忽略）
├── requirements.txt
├── .env.example
└── README.md
```

---

## 人设 YAML 格式

```yaml
id: my_persona
name: 张三
age: 28
occupation: 上班族
budget: "3000元以内"
personality: 谨慎、理性
pain_points:
  - 用手机看文件眼睛累
  - 会议记录效率低
objection_style: 喜欢横向比较，追问具体参数
purchase_goal: 找到最适合工作场景的设备

pressure_profile:
  price_sensitivity: 0.7      # 0~1，越高越在意价格
  trust_threshold: 0.8        # 越高越难建立信任
  patience: 0.5               # 越低越容易流失
  competitor_awareness: 0.6   # 越高越了解竞品
  decision_power: 0.9         # 越高越能自主决策
  emotion_volatility: 0.4     # 越高情绪波动越大
  need_urgency: 0.6           # 越高购买意向越急迫
  skepticism: 0.7             # 越高对销冠说法越怀疑
  bargaining_aggressiveness: 0.5  # 越高砍价越激进
```

---

## 阶段完成情况

| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段 1 | 项目骨架：config.py / runner.py CLI | ✅ |
| 阶段 2 | 输入与 schema：product.md + 3 persona + loaders | ✅ |
| 阶段 3 | LLM 层：llm.py + utils.py + --test-llm | ✅ |
| 阶段 4 | 双 Agent 单轮：persona/sales prompt + agents.py | ✅ |
| 阶段 5 | 多轮 Runner：run_session + 6 阶段路径 + rich 日志 | ✅ |
| 阶段 6 | Judge + Session Memory：按 interval 注入下一轮 | ✅ |
| 阶段 7 | Coach 复盘 + 输出 4 个文件 | ✅ |
| 阶段 8 | 三人设测试 + Prompt 调参 + README 完善 | ✅ |

---

## 后续扩展方向（v2 蓝图）

- **LangGraph 工作流**：把 Persona/Sales/Judge/Coach 改造为 LangGraph 节点，支持可视化调试
- **RAG 记忆库**：销冠从历史成功案例 JSONL 中实时检索话术，实现自进化
- **Web 看板**：FastAPI + WebSocket + Vue，实时查看对话并手动干预
- **人设管理**：Web 界面新建/编辑人设，一键启动对话
- **批量测试**：同一人设并发跑多场，统计成交率、平均难度、高频异议
- **数据库持久化**：SQLite/PostgreSQL 存储会话和经验，支持跨会话检索

---

## 技术栈

- Python 3.10+
- DeepSeek Chat（通过 OpenAI SDK 调用）
- Pydantic v2（数据校验）
- rich（控制台美化输出）
- python-dotenv、PyYAML
