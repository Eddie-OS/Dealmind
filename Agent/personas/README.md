# personas/ · 人设快照

这个目录是运行时的唯一人设来源。`02_persona_curator` 只扫描**本层**的
`.yaml` / `.yml` / `.json`，不递归子目录。

## 当前内容

- `db_XXXX__*.yaml` —— 从上游 `data/conversations.db` 一次性导出的 94 个人设快照。
  重新导出：`python tools/export_personas_from_db.py`（只读 DB，会覆盖同名文件）。
- `_examples/` —— 3 个示例人设，带下划线前缀的子目录不会被扫描，
  想拿它们做小规模试跑就复制回上一层。

## 加一个人设

直接在本层放一个 YAML，字段照抄 `_examples/` 里任意一个。`id` 必须唯一，
且只用文件名安全字符（重复 id 会被 curator 记为"排除"并跳过）。

## 只跑一部分

不要删文件，改 `config/pipeline.yaml`：

```yaml
personas:
  limit: 5              # 只跑前 5 个
  include_tags: [价格敏感]  # 只跑带这些标签的
  exclude_ids: [db_0023__Omar_(奥马尔)_-_宰兰理工学霸]
```

命令行 `--limit N` 会覆盖配置里的 `limit`。
