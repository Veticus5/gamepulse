{{ config(materialized='view') }}

-- One row per successful read of one of FiveM's own count files. The file
-- holds three numbers whose meaning is not documented; the first is the one
-- the site shows as players, and all three are kept.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/fivem/*.jsonl", {
        "ts": "VARCHAR", "url": "VARCHAR", "counts": "BIGINT[]", "ok": "BOOLEAN"
    }) }}
)

select
    url as source_url,
    {{ utc_timestamp('ts') }} as measured_at,
    counts[1] as players,
    counts,
    {{ collected_by('filename') }} as collected_by
from source
where ok
  and url is not null
  and counts[1] is not null
  and {{ utc_timestamp('ts') }} is not null
qualify row_number() over (partition by url, ts order by filename) = 1
