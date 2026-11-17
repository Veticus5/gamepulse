{{ config(materialized='view') }}

-- One row per stored snapshot of a game's review histogram. Columns are
-- spelled out so a missing key becomes NULL instead of changing the schema,
-- and a half-written last line is skipped.
select
    appid,
    try_strptime(fetched_at, '%Y-%m-%dT%H:%M:%SZ') as fetched_at,
    results.rollup_type as rollup_type,
    results.rollups as rollups,
    results.recent as recent
from read_json(
    '{{ var("raw_dir") }}/review_histogram/*.jsonl',
    format = 'newline_delimited',
    ignore_errors = true,
    columns = {
        appid: 'BIGINT',
        fetched_at: 'VARCHAR',
        results: 'STRUCT(
            rollup_type VARCHAR,
            rollups STRUCT("date" BIGINT, recommendations_up BIGINT, recommendations_down BIGINT)[],
            recent STRUCT("date" BIGINT, recommendations_up BIGINT, recommendations_down BIGINT)[]
        )'
    }
)
where appid is not null
  and try_strptime(fetched_at, '%Y-%m-%dT%H:%M:%SZ') is not null
