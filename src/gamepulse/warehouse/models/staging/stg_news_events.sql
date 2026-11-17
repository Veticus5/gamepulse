{{ config(materialized='view') }}

-- One row per news item the classifier has labelled: its latest label.
-- This is model output, kept apart from the facts it describes.
with source as (
    select *
    from {{ read_jsonl(var("derived_dir") ~ "/news_events/*.jsonl", {
        "gid": "VARCHAR", "appid": "BIGINT", "event_type": "VARCHAR", "effective_date": "VARCHAR",
        "summary": "VARCHAR", "importance": "VARCHAR", "confidence": "DOUBLE",
        "model": "VARCHAR", "prompt_version": "VARCHAR", "classified_at": "VARCHAR"
    }) }}
)

select
    gid,
    appid,
    event_type,
    try_cast(effective_date as date) as effective_date,
    summary,
    importance,
    confidence,
    model,
    prompt_version,
    {{ utc_timestamp('classified_at') }} as classified_at
from source
where gid is not null
qualify row_number() over (partition by gid order by classified_at desc nulls last) = 1
