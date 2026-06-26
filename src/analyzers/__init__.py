"""Handbook Analysis（HA）模块 · 分析器集合

子模块：
  - analysis_runner: 任务编排（拉取 turns → 分类 → 评分 → 聚合）
  - handbook_classifier: LLM 多标签分类器（A2）
  - handbook_scorer: 6 维度评分器（A3）
  - report_aggregator: 报告聚合（覆盖率/短板/Persona/Handbook 建议）（A4）
  - handbook_extractor: 从 parsed_text 抽 1/3/3/5/9/10（B1）
"""
