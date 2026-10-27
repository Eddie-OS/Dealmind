# 01 · 产品手册解析 Agent

把你丢进 `inbox/` 的产品手册，变成销冠对话时能直接引用的结构化剧本。
本次 run 里**只跑一次**，产物被后面所有会话共享。

## 输入

| 来源 | 说明 |
|------|------|
| `inbox/*` | pdf / docx / pptx / xlsx / md / txt / json，可放多份，会按文件名排序拼接 |
| `config/pipeline.yaml → handbook` | `doc_type`（auto/structured/playbook）与正文字数上限 |

`inbox/` 里放 `.json` 且内容已经是结构化手册时，直接采用，不再调模型。
这条路径用于"上次解析结果拿来复用"，省一次抽取成本。

## 输出

| 文件 | 内容 |
|------|------|
| `runs/<run_id>/01_handbook/handbook.json` | 结构化手册，后续会话的事实来源 |
| `runs/<run_id>/01_handbook/handbook.md` | 同一份内容的人类可读版 |
| `runs/<run_id>/01_handbook/raw_text.md` | 解析出的原始正文，用于核对抽取有没有漏 |
| `runs/<run_id>/steps/01_handbook_ingest/*.md` | 每个文件的解析步骤与抽取调用 |

结构化手册有两种形态，抽取器按文档内容自动选：

- `structured`（默认）：1 句定位 / 3 卖点 / 3 竞品 / 5 参数 / 9 FAQ / 10 演示动作
- `playbook_v1`：按人设分组的四章销售流程（开场 / 卖点 / 竞品 / 问答）

## 与其他 agent 的关系

- 下游全体：`handbook.json` 通过 `shared/dbfakes.set_active_handbook()` 挂载为
  全局激活手册，销冠每一轮的 prompt 里都会注入它。
- `08_content_guard`：手册里的数字是护栏判定"这个价格是不是编的"的主要依据。
  手册解析得越全，护栏误杀真话的概率越低。

## 单独运行

```bash
python 01_handbook_ingest/run.py --dry-run          # 不调模型，验证解析链路
python 01_handbook_ingest/run.py                    # 真实抽取，写进最新 run
python 01_handbook_ingest/run.py --run-id run_xxx   # 写进指定 run
```

## 已知边界

- pdf/docx/pptx/xlsx 依赖 `pypdf` / `python-docx` / `python-pptx` / `openpyxl`，
  缺哪个就跳过哪种格式并在 MD 里记一条警告，不会中断。
- 抽取是**单次调用**拿全部结构。手册特别长时先截断再抽，截断点会写进警告。
