-- One row per game with what is known about it right now: the latest player
-- count, today's price, the last finished day of reviews and its episodes.
with ids as (
    select appid from {{ ref('stg_games') }}
    union
    select appid from {{ ref('stg_player_counts') }}
    union
    select appid from {{ ref('int_review_periods') }}
),

players as (
    select
        appid,
        arg_max(player_count, measured_at) as players_now,
        max(measured_at) as players_measured_at
    from {{ ref('stg_player_counts') }}
    group by 1
),

peak as (
    select c.appid, max(c.player_count) as players_peak_24h
    from {{ ref('stg_player_counts') }} as c
    join players as p using (appid)
    where c.measured_at > p.players_measured_at - interval 24 hour
    group by 1
),

price as (
    select
        appid,
        arg_max(final_price_cents, day) as final_price_cents,
        arg_max(regular_price_cents, day) as regular_price_cents,
        arg_max(discount_percent, day) as discount_percent,
        arg_max(currency, day) as currency,
        max(day) as price_day
    from {{ ref('int_prices_daily') }}
    group by 1
),

reviews as (
    select
        appid,
        arg_max(reviews, period_start) as reviews_last_day,
        arg_max(share_positive, period_start) as share_positive_last_day,
        max(period_start) as reviews_day
    from {{ ref('int_review_periods') }}
    where grain = 'day' and is_complete
    group by 1
),

episodes as (
    select
        appid,
        count(*) as episodes,
        count(*) filter (where is_open) as open_episodes,
        max(period_end) as last_episode_end
    from {{ ref('anomaly_episodes') }}
    group by 1
)

select
    ids.appid,
    g.name,
    g.appid is not null as is_tracked,
    players.players_now,
    players.players_measured_at,
    peak.players_peak_24h,
    price.final_price_cents,
    price.regular_price_cents,
    price.discount_percent,
    price.currency,
    price.price_day,
    reviews.reviews_last_day,
    reviews.share_positive_last_day,
    reviews.reviews_day,
    coalesce(episodes.episodes, 0) as episodes,
    coalesce(episodes.open_episodes, 0) as open_episodes,
    episodes.last_episode_end
from ids
left join {{ ref('stg_games') }} as g using (appid)
left join players using (appid)
left join peak using (appid)
left join price using (appid)
left join reviews using (appid)
left join episodes using (appid)
