# 13 性能、容量与成本

## 1. 核心请求延迟构成（定性）

单场一轮近似：

```
T_round ≈ T_persona_llm + T_sales_llm[+ N_tool * (T_tool + T_llm)] + 1/interval * (T_mem + T_judge)
```

另加：preflight（会前，含搜索+LLM）、结束 Coach、persist、WS。  
前端可忽略。DB 写入不是主因。**模型 RT 占绝对大头。**

Batch：多场并行受 `BATCH_SESSION_CONCURRENCY` 与 `LLM_MAX_IN_FLIGHT` 背压。  
分析：`ANALYSIS_TURN_WORKERS` 但全局 semaphore 12，实际会排队。

## 2. 已实现限额

| 旋钮 | 默认 | 作用 |
|---|---|---|
| DM_MAX_CONCURRENT_SESSIONS | 3 | 实时 429 |
| Session 线程池 | 8 | runner |
| BATCH_SESSION_CONCURRENCY | 代码 3 / example 8 | 批量 |
| LLM_MAX_IN_FLIGHT | 12 | 全局 |
| ANALYSIS_TURN_WORKERS | 16 | 分析 |
| max_rounds | 会话配置 | 轮次帽 |
| max_tool_loops | 3（顶 8） | 工具放大 |
| recent_history | 10 | 上下文 |
| RAG chunk | 600 字 | 上下文 |
| tool result | 3000 字 | 上下文 |
| Embed 预加载 | 开 | 避峰 |

无 circuit breaker、无用户级 QPS、无日预算。

## 3. 最坏放大

- Fan-out：批量 8 场 × 每场 20 轮 ×（2 + 工具3 + 1/6 Judge + 1/6 Memory）+ Coach。
- 工具循环每轮最多 8 次 LLM。
- 分析 745 turn × 每 turn 至少 1 次辅助 LLM。
- 上下文膨胀：handbook + fact + RAG + 10 轮历史 + 工具回填。
- 重试：`MAX_RETRIES` 线性放大费用。

## 4. 成本公式（勿当精确账单）

设：

- \(C_p\)：主模型（销冠/人设）每百万 token 单价  
- \(C_a\)：辅助模型单价  
- \(T_{in}, T_{out}\)：每调用平均 token  

则一场约：

\[
Cost_{session} \approx R \cdot (C_p \cdot T_{sales} + C_p \cdot T_{persona}) + \frac{R}{I_j} C_a T_{judge} + \frac{R}{I_m} C_a T_{mem} + C_a T_{coach} + Tools
\]

批量：\(\times N_{sessions}\)；分析另计 \(N_{turns} \cdot C_a T_{cls}\)。

**所需数据**：把 `_log_usage` 落库按 session_id 聚合；记录模型名与 cache hit。当前只有 console。

## 5. 容量模型

| 场景 | 约束 |
|---|---|
| 单操作员实时 | 3 场同时（默认） |
| 2GB 机器 | embedder + 3 场即可顶满；harden MemoryMax 1.4G |
| 14GB / SLA 44 场 2h | 需把 BATCH 调到 8 且 LLM 槽足够；[待验证] 未复现 SLA |
| SQLite | WAL 可读写并发；不适合多机 |

## 6. 优化机会（具体）

1. usage 落库 + RunningStatus 展示 session 成本。
2. 批量默认与 `.env.example` 对齐并写进文档，避免 3 vs 8 认知差。
3. Sales 无工具时不要走 tool 循环。
4. Judge/Memory interval 已在批量加大——保持。
5. 分析 worker > LLM 槽会造成空转线程，可对齐为 12。
6. 启动预加载与 `DM_PRELOAD_EMBEDDER=0` 开发开关已存在，文档应写进 README。
