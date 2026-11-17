{{ config(materialized='view') }}

-- One row per successful measurement of a game's current player count.
-- The same moment collected twice (locally and on GitHub) is kept once.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/ccu/*.jsonl", {
        "ts": "VARCHAR", "appid": "BIGINT", "player_count": "BIGINT", "ok": "BOOLEAN"
    }) }}
)

select
    appid,
    {{ utc_timestamp('ts') }} as measured_at,
    player_count,
    {{ collected_by('filename') }} as collected_by
from source
where ok
  and appid is not null
  and player_count is not null
  and {{ utc_timestamp('ts') }} is not null
qualify row_number() over (partition by appid, ts order by filename) = 1
