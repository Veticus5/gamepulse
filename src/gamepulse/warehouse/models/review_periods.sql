-- Review counts per game and period. Steam gives the whole history rolled
-- up by month (or by week for newer games) and the last 30 days by day.
-- Every snapshot repeats the history, so rollups come from the newest
-- snapshot only; days are kept from all snapshots, newest value winning,
-- which lets the daily history grow past 30 days over time.
with snapshots as (
    select * from {{ ref('stg_review_snapshots') }}
),

latest as (
    select * from snapshots
    qualify row_number() over (partition by appid order by fetched_at desc) = 1
),

unnested as (
    select appid, fetched_at, rollup_type as grain, unnest(rollups) as r
    from latest
    where rollup_type in ('week', 'month')
    union all
    select appid, fetched_at, 'day' as grain, unnest(recent) as r
    from snapshots
),

typed as (
    select
        appid,
        grain,
        cast(make_timestamp(r.date * 1000000) as date) as period_start,
        coalesce(r.recommendations_up, 0) as positive,
        coalesce(r.recommendations_down, 0) as negative,
        fetched_at
    from unnested
    where r.date is not null
),

newest as (
    select * from typed
    qualify row_number() over (partition by appid, grain, period_start order by fetched_at desc) = 1
),

bounded as (
    select
        *,
        cast(case grain
            when 'month' then period_start + interval 1 month
            when 'week' then period_start + interval 7 day
            else period_start + interval 1 day
        end as date) as period_end
    from newest
)

select
    appid,
    grain,
    period_start,
    period_end,
    positive,
    negative,
    positive + negative as reviews,
    case when positive + negative > 0 then positive / (positive + negative) end as share_positive,
    -- A period still running when the snapshot was taken has partial counts.
    period_end <= fetched_at as is_complete,
    fetched_at
from bounded
