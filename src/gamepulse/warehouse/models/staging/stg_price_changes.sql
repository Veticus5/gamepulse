{{ config(materialized='view') }}

-- One row per change of a game's Steam price, from IsThereAnyDeal. The
-- collector replaces a game's file on every fetch, so each file is one
-- consistent log; `log_since` and `fetched_at` say which stretch it covers.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/price_history/*.jsonl", {
        "fetched_at": "VARCHAR", "since": "VARCHAR", "appid": "BIGINT", "ts": "VARCHAR",
        "currency": "VARCHAR", "initial": "BIGINT", "final": "BIGINT", "discount_percent": "BIGINT"
    }) }}
)

select
    appid,
    {{ utc_timestamp('ts') }} as changed_at,
    currency,
    initial as regular_price_cents,
    final as final_price_cents,
    coalesce(discount_percent, 0) as discount_percent,
    {{ utc_timestamp('since') }} as log_since,
    {{ utc_timestamp('fetched_at') }} as fetched_at
from source
where appid is not null
  and {{ utc_timestamp('ts') }} is not null
  and {{ utc_timestamp('since') }} is not null
  and {{ utc_timestamp('fetched_at') }} is not null
qualify row_number() over (partition by appid, ts order by fetched_at desc) = 1
