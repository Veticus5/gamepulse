-- Periods whose reviews differ clearly from what was usual for that game.
-- Everything here is arithmetic; no model takes part.
with scored as (
    select
        *,
        -- Spread of the share of positive reviews: the larger of what the
        -- game's own history shows and what chance alone gives at this
        -- number of reviews, never below one percentage point.
        (share_positive - baseline_share) / greatest(
            1.4826 * baseline_share_mad,
            sqrt(baseline_share * (1 - baseline_share) / reviews),
            0.01
        ) as share_z,
        reviews / baseline_reviews as volume_ratio,
        (ln(reviews) - baseline_ln_reviews) / greatest(1.4826 * baseline_ln_reviews_mad, 0.1) as volume_z
    from {{ ref('review_baselines') }}
    where baseline_periods >= {{ var('min_baseline_periods') }}
),

found as (
    select
        *,
        case when share_positive < baseline_share then 'review_score_drop' else 'review_score_rise' end as kind,
        share_positive as value,
        baseline_share as baseline,
        share_positive - baseline_share as deviation,
        share_z as score
    from scored
    where reviews >= {{ var('min_reviews') }}
      and abs(share_positive - baseline_share) >= {{ var('min_share_shift') }}
      and abs(share_z) >= {{ var('z_threshold') }}

    union all

    select
        *,
        'review_volume_spike' as kind,
        reviews as value,
        baseline_reviews as baseline,
        volume_ratio as deviation,
        volume_z as score
    from scored
    where reviews >= {{ var('volume_min_reviews') }}
      and volume_ratio >= {{ var('volume_ratio') }}
      and volume_z >= {{ var('z_threshold') }}
)

select
    md5(concat_ws('|', appid, grain, period_start, kind)) as anomaly_id,
    appid,
    grain,
    period_start,
    period_end,
    kind,
    value,          -- share of positive reviews (0-1), or number of reviews for a volume spike
    baseline,       -- the usual value before this period
    deviation,      -- value minus baseline for scores; value divided by baseline for volume
    score,          -- robust z-score; negative means below the usual
    reviews,
    positive,
    negative,
    baseline_periods,
    fetched_at as data_as_of
from found
