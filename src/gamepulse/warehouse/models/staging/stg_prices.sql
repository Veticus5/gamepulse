{{ config(materialized='view') }}

-- One row per read of a game's price in the US Steam store. Amounts are in
-- cents. `priced` is false for a game that is free or not for sale.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/prices/*.jsonl", {
        "ts": "VARCHAR", "appid": "BIGINT", "priced": "BOOLEAN", "currency": "VARCHAR",
        "initial": "BIGINT", "final": "BIGINT", "discount_percent": "BIGINT"
    }) }}
)

select
    appid,
    {{ utc_timestamp('ts') }} as observed_at,
    coalesce(priced, false) as priced,
    currency,
    initial as regular_price_cents,
    final as final_price_cents,
    coalesce(discount_percent, 0) as discount_percent,
    {{ collected_by('filename') }} as collected_by
from source
where appid is not null
  and {{ utc_timestamp('ts') }} is not null
qualify row_number() over (partition by appid, ts order by filename) = 1
