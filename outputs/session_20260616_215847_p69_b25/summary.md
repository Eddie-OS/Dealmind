# 会话摘要

| 字段 | 值 |
|------|-----|
| session_id | `session_20260616_215847_p69_b25` |
| 话题 | HUAWEI MatePad Air in-store sales simulation |
| 人设 | 俊 Tuấn（None，预算None） |
| 最终结果 | **DEAL_DONE** |
| 总轮数 | 16 |
| 最终阶段 | 方案匹配与价值锚定 |

## 会话画像记忆

- **核心需求**：User wants to see the sustained GPU performance of the MatePad Air (Kirin 9000E) after a 20-minute Wildlife Extreme stress test loop, specifically whether it stays above 2,500, and compare the thermal throttle curve to Snapdragon 8 Gen 1.
- **预算边界**：
- **情绪状态**：Impressed by peak score but still skeptical about sustained performance; wants concrete data and thermal graph before making a decision.
- **主要异议**：
  - User doubted whether the device can hold 90fps in PUBG after 20 minutes without throttling.
  - User questioned the chip model and wanted exact Kirin model, cores, and GPU name.
  - User wants sustained performance proof, not just peak scores; concerned about thermal throttling after 15 minutes.
- **避免重复**：
  - Do not repeat that you don't have third-party frame-rate logs or that you won't fake numbers.
  - Do not repeat the suggestion to run the demo again (already done).
  - Do not repeat that 'Kirin chipset' is vague or apologize again for it.
  - Do not repeat the peak score without showing sustained performance.
- **下一步建议**：Show the final 20-minute Wildlife Extreme stress test score and thermal graph; highlight that at 15 minutes it was 2,623 (above 2,500 and above Snapdragon 8 Gen 1's throttled score). Then ask the user if they want to proceed with the PUBG frame-counter test or discuss purchase.

## Coach 复盘

**结果分析**：成交的根本原因是销冠通过现场性能测试（Wildlife Extreme和PUBG帧率测试）直接证明了产品价值，满足了客户对持续性能的硬性需求。关键转折点在轮次3（客户要求热节流曲线）和轮次5（销冠提供15分钟分数2,623，客户认可但要求20分钟最终分数），轮次7（20分钟分数2,587，客户承认性能并同意谈价格）是决定性转折点。

**人设难度**：8/10 — 客户技术知识丰富（competitor_awareness=0.9），怀疑度高（skepticism=0.9），要求具体数据验证，且决策权完全在自己（decision_power=1.0），不易被话术打动。但一旦证明价值，成交意愿强（need_urgency=0.6）。

**人设洞察**：俊Tuấn型客户是技术极客，极度关注持续性能（热节流、帧率锁定），对数据敏感，信任阈值高（0.8），但一旦证明价值，决策迅速（decision_power=1.0）。异议风格直接，要求具体证据而非宣传话术。

### 有效策略
- 第5轮 [SPIN-影响提问]：通过反问引导客户对比自身设备，强化了MatePad Air的散热优势，让客户自己意识到竞品不足。
  > 客户问'你的Gen 1在节流后稳定在多少？'，销冠反问'What does your Gen 1 settle at after throttling?'
- 第7轮 [证据3B-佐证带证据]：用具体数据证明持续性能超过客户阈值，直接打消了客户对'冲刺后爬行'的疑虑，为后续定价谈判铺平道路。
  > 销冠提供20分钟最终分数2,587并对比Snapdragon 8 Gen 1的峰值和节流后分数。
- 第11轮 [行动3A-现场动作]：利用稀缺性（库存流动快）和紧迫感（现场预留），推动客户从意向到行动，最终客户同意预留。
  > 销冠说'Want me to reserve one now? Stock moves fast on this config.'

### 失效操作
- 第1轮 [软钩子（soft_hook）]：客户要求看热节流曲线，销冠却回应调单核，偏离客户需求，且未提供图形数据，导致客户继续施压。
  > 销冠说'准确价格我让同事现场给您调单核一下'，但对话中未实际执行调单核动作。
- 第3轮 [软钩子（soft_hook）]：重复无效话术，未直接回应客户核心需求（热图），浪费轮次，且未展示店内演示能力。
  > 销冠再次说'准确价格我让同事现场给您调单核一下'，但客户明确要求20分钟分数和热图。

### 销售经验（可写入培训手册）
1. 1. 面对技术型客户，必须用具体数据（分数、帧率、温度曲线）而非模糊描述来证明性能。
2. 2. 客户要求特定测试时，立即执行，不要用无关话术（如调单核）拖延。
3. 3. 线下店应主动邀请客户上手操作测试，而非仅口头报告数据。
4. 4. 报价前先确认客户预算范围，避免直接报中间价，可试探性报价。
5. 5. 在S3阶段应使用更多3A动作（如现场演示、对比），而非仅靠口头证据。

### 更优话术模板
- **客户要求看热节流曲线图。**
  > 先生，我马上在平板上运行Wildlife Extreme循环测试，您看这个实时帧率曲线——15分钟后如果低于{阈值}，这台机器您不用考虑。
- **客户质疑价格是否在13.5-22.5M VND范围。**
  > 先生，您看这台MatePad Air bundle（键盘+笔+WPS）官方定价是{价格}，但今天店内活动可以给您{折扣}，实际到手{最终价}，比您预算上限还低{差额}。
- **客户要求看PUBG帧率测试。**
  > 没问题，我打开PUBG，您亲自操作，我记录帧率。如果12分钟内掉帧超过{阈值}，这台机器您不用买。

### 可复用策略模式
- **性能对比锚定法**
  - 使用条件：客户是技术型，关注持续性能。
  - 示例：提供竞品（如Snapdragon 8 Gen 1）的节流数据，与自家产品对比，用具体分数和曲线证明优势。
- **现场测试破信任法**
  - 使用条件：客户要求验证特定性能指标。
  - 示例：立即在店内设备上运行客户指定的测试（如Wildlife Extreme、PUBG帧率），实时展示结果。
- **稀缺性紧迫成交法**
  - 使用条件：客户已认可产品价值，但犹豫是否立即购买。
  - 示例：告知库存有限或活动即将结束，主动提出预留，降低客户决策成本。

---
*导出时间：20260616_220625*