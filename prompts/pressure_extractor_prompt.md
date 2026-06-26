你是一名消费者行为分析师。请阅读下方"用户角色 Prompt"，根据角色的设定、价值观、消费习惯、语言风格，给出该角色在销售对话中的 **9 维量化压力参数**。

每个维度都是 0.0 到 1.0 之间的小数，数值越高代表该倾向越强烈。请基于角色描写做出客观推断，不要随意给中间值兜底。

---

## 角色 Prompt

{persona_prompt}

---

## 9 个维度定义

1. **price_sensitivity**（价格敏感度）：0=完全不在意价格，1=极度看重价格、会主动砍价/比价。
2. **trust_threshold**（信任阈值）：0=容易被说服，1=必须看到强证据/案例/售后承诺才信任。
3. **patience**（耐心程度）：0=极度没耐心，销售一啰嗦立刻不耐烦；1=愿意听完所有讲解再决定。
4. **competitor_awareness**（竞品认知度）：0=不了解市面竞品，1=熟悉所有主流竞品并主动拿来压价或对比。
5. **decision_power**（决策权）：0=必须问家人/老板/朋友，1=自己说了算立刻能下单。
6. **emotion_volatility**（情绪波动）：0=全程冷静理性，1=容易被销售刺激情绪起伏甚至发火。
7. **need_urgency**（需求紧迫度）：0=只是随便看看，1=今天就必须解决问题/今天就要买。
8. **skepticism**（怀疑度）：0=相信销售说的每句话，1=质疑销售承诺，要求每条卖点都有实证。
9. **bargaining_aggressiveness**（砍价强度）：0=接受原价绝不砍，1=每次都狠砍且不接受原价。

---

## 输出规范

只输出一个合法 JSON 对象，不要包含 markdown 代码块、解释或任何额外文字。字段名严格一致，数值保留 2 位小数：

{
  "price_sensitivity": 0.50,
  "trust_threshold": 0.50,
  "patience": 0.50,
  "competitor_awareness": 0.50,
  "decision_power": 0.50,
  "emotion_volatility": 0.50,
  "need_urgency": 0.50,
  "skepticism": 0.50,
  "bargaining_aggressiveness": 0.50
}
