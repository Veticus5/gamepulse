-- Episodes: runs of neighbouring unusual periods (see anomalies). This is
-- the unit shown in the interface and the unit the agent explains.
with periods as (
    select
        episode_id,
        appid,
        grain,
        direction,
        period_start,
        period_end,
        any_value(reviews) as reviews,
        any_value(positive) as positive,
        any_value(negative) as negative,
        any_value(baseline_share) as baseline_share,
        any_value(baseline_reviews) as baseline_reviews,
        any_value(volume_ratio) as volume_ratio,
        bool_or(kind = 'review_volume_spike') as volume_spike,
        max(data_as_of) as data_as_of
    from {{ ref('anomalies') }}
    group by all
),

last_finished as (
    select appid, grain, max(period_end) as period_end
    from {{ ref('int_review_baselines') }}
    group by all
),

grouped as (
    select
        episode_id,
        appid,
        grain,
        direction,
        min(period_start) as period_start,
        max(period_end) as period_end,
        count(*) as periods,
        cast(sum(reviews) as bigint) as reviews,
        cast(sum(positive) as bigint) as positive,
        cast(sum(negative) as bigint) as negative,
        sum(positive) / sum(reviews) as share_positive,
        -- What was usual just before the episode began.
        arg_min(baseline_share, period_start) as baseline_share,
        arg_min(baseline_reviews, period_start) as baseline_reviews,
        bool_or(volume_spike) as volume_spike,
        max(volume_ratio) as peak_volume_ratio,
        arg_max(period_start, reviews) as busiest_period_start,
        max(data_as_of) as data_as_of
    from periods
    group by all
)

select
    g.*,
    -- Ends with the newest finished period: it may still be going on.
    g.period_end = l.period_end as is_open
from grouped as g
join last_finished as l using (appid, grain)
