---
# Stage A: 项目基础升级与全局配置

**目标**：升级项目骨架，支持多产品、多 Persona 批量跑，配置全局 settings 和日志异常处理。

**主要任务**：
- 升级目录结构，新增 data/chroma、exports、sessions。
- 升级 runner.py CLI 支持批量跑参数。
- 配置全局 settings，支持多 Agent temperature。
- 添加全局日志和异常处理。

**输出文件/产物**：
- 升级后的项目骨架
- runner.py CLI

**验收标准**：
- CLI 可打印配置和路径
- 最小示例可运行

**Vibe Coding 提示词**：
你是顶级全栈 Python 工程师。请在现有 MVP 基础上升级最终版骨架，支持多产品、多 Persona 批量跑；增加 data/chroma/ 存储 Embedding；runner.py 支持 --products_dir, --personas_dir, --batch_run, --max_rounds, --judge_interval, --memory_interval；配置全局 Agent temperature；添加日志和异常处理；输出最小示例打印配置与路径，不调用 Agent.

---
# Stage B: 产品知识 RAG 与三层记忆

**目标**：实现 Product KB、Sales Experience、Session Memory 并支持 RAG 检索。

**主要任务**：
- 构建 Product Knowledge Embedding（Chroma/FAISS）
- 构建 Sales Experience 数据结构（候选/正式库）
- Session Memory 每 memory_interval 更新
- 提供 get_product_hits、get_experience_hits 接口

**输出文件/产物**：
- get_product_hits, get_experience_hits, session_memory JSON

**验收标准**：
- Session Memory 更新正常
- 检索接口返回 JSON 正确

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现最终版 RAG 和三层记忆体系；构建 Product Knowledge Embedding，支持 Chroma/FAISS；构建 Sales Experience 数据结构（候选/正式库）；Session Memory 每 memory_interval 更新；提供 get_product_hits(state), get_experience_hits(state) 接口；支持 JSON 输出并注入 Agent prompt；失败时有 fallback，不崩溃.

---
# Stage C: 四 Agent 全流程实现

**目标**：实现 Persona、Sales Champion、Judge、Coach 四 Agent 全流程调用。

**主要任务**：
- Persona Agent：压力参数 + 阶段化行为输出 JSON
- Sales Champion Agent：读取 product_hits、experience_hits、session_memory + Judge 指令生成策略 JSON
- Judge Agent：每 judge_interval 轮调用，输出阶段、end_status、avoid_repeating
- Coach Agent：会话结束调用生成 review.json、script_candidates.md、lessons_candidate.jsonl

**输出文件/产物**：
- agents.py、四 Agent Prompt

**验收标准**：
- 四 Agent 单轮及多轮循环可运行
- JSON 输出严格

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现最终版四 Agent；Persona Agent：压力参数 + 阶段化行为输出 JSON；Sales Champion Agent：读取 product_hits、experience_hits、session_memory + Judge 指令生成策略 JSON；Judge Agent：每 judge_interval 轮调用，输出阶段、end_status、avoid_repeating；Coach Agent：会话结束调用生成 review.json、script_candidates.md、lessons_candidate.jsonl；Agent 输出严格 JSON，带兜底和错误日志；Runner 集成四 Agent，按阶段循环 20-50 轮.

---
# Stage D: 阶段驱动与结束条件

**目标**：实现六阶段销售流程及多种结束条件。

**主要任务**：
- 六阶段流程控制
- 每轮更新 stage 与 session_memory
- 支持 DEAL_DONE、WALK_AWAY、FOLLOW_UP、TIMEOUT 结束条件

**输出文件/产物**：
- get_stage_by_round 函数、state.current_stage 更新

**验收标准**：
- 阶段推进正确
- 结束条件触发正常

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现六阶段销售流程驱动；每轮 Persona/Sales/Judge 调用后更新 session_memory；支持 DEAL_DONE、WALK_AWAY、FOLLOW_UP、TIMEOUT；控制台输出轮次与阶段变更；循环异常时保留历史.

---
# Stage E: 输出资产与复盘

**目标**：会后调用 Coach Agent 生成结构化复盘和培训资产。

**主要任务**：
- 生成 dialogue.json、review.json、script_candidates.md、lessons_candidate.jsonl
- 生成 FAQ 和 Training Guide 候选
- 逐行追加 lessons_candidate.jsonl

**输出文件/产物**：
- dialogue.json, review.json, script_candidates.md, lessons_candidate.jsonl

**验收标准**：
- 文件生成完整，可直接用于培训

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现最终版会话资产输出；调用 Coach Agent 生成 review；保存 dialogue.json、review.json、script_candidates.md、lessons_candidate.jsonl；逐行追加 lessons_candidate.jsonl；生成 FAQ/Training Guide 候选；输出目录 outputs/session_YYYYMMDD_HHMMSS_{persona_id}/；即使 Coach 调用失败也保存 dialogue.json；控制台打印保存日志.

---
# Stage F: 批量测试与统计

**目标**：支持多 Persona、多产品批量跑，并生成统计汇总。

**主要任务**：
- 批量执行 session
- 生成异议排行榜、话术候选汇总、经验命中率统计
- 支持 Web 看板接口预留

**输出文件/产物**：
- 汇总 JSON、异议排行榜、话术候选汇总

**验收标准**：
- 批量会话无中断
- 统计数据正确

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现批量测试；支持多 Persona、多产品批量跑 session；汇总异议排行榜、话术候选汇总、经验命中率统计；每场会话独立目录；支持后续 Web 看板接入（FastAPI + WebSocket）；日志清晰，每场异常不影响其他会话.

---
# Stage G: Web 看板与 Training Guide 流水线

**目标**：实现 Vue3 SPA 展示、FastAPI 实时接口及 Training Guide 输出。

**主要任务**：
- Vue3 SPA 展示会话现场、历史、经验库、指标统计、导出中心
- FastAPI + WebSocket 提供实时数据
- Training Guide 页面渲染候选话术、FAQ、错题示范，并导出

**输出文件/产物**：
- Vue3 前端、FastAPI 接口、Training Guide 页面

**验收标准**：
- 页面展示正确
- 数据实时更新
- Training Guide 可导出

**Vibe Coding 提示词**：
你是顶级全栈工程师，实现最终版 Web 看板和 Training Guide 流水线；Vue3 SPA 展示会话现场、历史对话、经验库管理、指标统计、导出中心；FastAPI + WebSocket 提供实时数据接口；Training Guide 页面自动渲染候选话术、FAQ、错题示范；支持 CSV / JSON / MD 导出；保证与 Runner / Agent 输出兼容.

