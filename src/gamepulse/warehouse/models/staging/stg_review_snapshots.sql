{{ config(materialized='view') }}

-- One row per stored snapshot of a game's review histogram.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/review_histogram/*.jsonl", {
        "appid": "BIGINT",
        "fetched_at": "VARCHAR",
        "results": 'STRUCT(rollup_type VARCHAR, rollups STRUCT("date" BIGINT, recommendations_up BIGINT, recommendations_down BIGINT)[], recent STRUCT("date" BIGINT, recommendations_up BIGINT, recommendations_down BIGINT)[])'
    }) }}
)

select
    appid,
    {{ utc_timestamp('fetched_at') }} as fetched_at,
    results.rollup_type as rollup_type,
    results.rollups as rollups,
    results.recent as recent
from source
where appid is not null
  and {{ utc_timestamp('fetched_at') }} is not null
