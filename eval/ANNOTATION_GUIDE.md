# RAG 评测集标注说明

`test_cases.json` 中用于检索评测的用例必须填写：

- `retrieval_eval: true`：明确标记该用例进入检索指标统计与标注校验。
- `expected_route`：`faq`、`worldbook` 或 `anime`。
- `relevant_texts`：预期命中文档中稳定存在的短文本；不要填写模型可能自行生成的词。
- `relevance_grades`（可选）：以 `relevant_texts` 的文本为 key，取 1～3；3 表示直接回答问题的核心证据。
- `key_facts`：最终回答必须覆盖的事实，用于生成质量评测。

新增或修改知识库后，应先人工确认这些文本确实存在于当前文档，再运行：

```powershell
python -m eval.runner
```

评测报告会写入 `eval/eval_report.json`。原始检索排名、分数和来源会写入 `db/rag_retrieval_traces.sqlite3`，可用于分析漏召回、排序错误和路由错误。
