-- One row per game and UTC day on which its Steam price is known: the
-- highest discount and the lowest price seen that day.
--
-- Two sources are merged. Our own collector reads the price every half hour,
-- but only since November 2026. The log of price changes from IsThereAnyDeal
-- reaches back further: a price holds from the change that set it to the
-- next change, and the last one until the day the log was fetched. The day a
-- sale ends counts as a sale day, because part of it was.
with observed as (
    select
        appid,
        cast(observed_at as date) as day,
        max(discount_percent) as discount_percent,
        min(final_price_cents) as final_price_cents,
        max(regular_price_cents) as regular_price_cents,
        max(currency) as currency
    from {{ ref('stg_prices') }}
    group by 1, 2
),

changes as (
    select
        *,
        cast(changed_at as date) as first_day,
        coalesce(
            cast(lead(changed_at) over (partition by appid order by changed_at) as date),
            cast(fetched_at as date)
        ) as last_day
    from {{ ref('stg_price_changes') }}
),

logged as (
    select
        appid,
        cast(unnest(generate_series(first_day, last_day, interval 1 day)) as date) as day,
        discount_percent,
        final_price_cents,
        regular_price_cents,
        currency
    from changes
    where last_day >= first_day
),

combined as (
    select *, true as is_observed from observed
    union all
    select *, false as is_observed from logged
)

select
    appid,
    day,
    max(discount_percent) as discount_percent,
    min(final_price_cents) as final_price_cents,
    max(regular_price_cents) as regular_price_cents,
    max(currency) as currency,
    bool_or(is_observed) as from_own_collection,
    bool_or(not is_observed) as from_price_log
from combined
group by 1, 2
