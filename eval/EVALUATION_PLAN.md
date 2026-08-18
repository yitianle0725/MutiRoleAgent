# RAG Evaluation Plan

## Completed

- Retrieval: Recall@K, Precision@K, MRR, and NDCG@K.
- Generation: Faithfulness, Answer Relevancy, Context Relevancy, and Context Recall.
- Reports include per-case details and summary values.
- Regression threshold loading accepts all eight metric names.
- Missing annotations or contexts produce `null`, not a fabricated zero.

## Current Measurement Contract

Each retrieval case should provide `relevant_texts`; graded ranking may add
`relevance_grades`. Each generation case should provide `key_facts`, and each
run result should provide `contexts` (the runner currently mirrors tool output
into this field).

The generation metrics currently use a deterministic lexical evaluator. This
keeps CI reproducible and offline, but it is not a replacement for a RAGAS
LLM-as-Judge implementation. A later phase can add a judge adapter while
keeping the same report schema.

## Next Iterations

1. Expand annotated cases to cover every knowledge collection and query type.
2. Capture raw retrieved documents separately from tool output.
3. Add human-reviewed reference answers for high-value cases.
4. Compare the lexical evaluator with a judge model on a sampled set.
5. Tune `eval/thresholds.json` from a recorded baseline after each dataset revision.

## Historical conversation evaluation

The production SQLite history is a useful behavioural dataset. Run
`python -m eval.history_runner --limit 100` to write
`eval/history_eval_report.json`. It evaluates recorded user/assistant pairs
without making new model calls. The report records whether a turn was answered,
answer length, and query-term overlap, plus availability of optional `ranx` and
`ragas` integrations. Ground-truth retrieval labels are required before
Recall/Precision/MRR can be meaningfully computed; historical transcripts alone
must not be treated as relevance annotations.

`eval/external_metrics.py` contains lazy adapters: use
`build_ranx_inputs`/`score_with_ranx` for labeled ranking runs and
`score_with_ragas` with an explicitly supplied judge model for generation
metrics. The default commands never upload private transcripts.
