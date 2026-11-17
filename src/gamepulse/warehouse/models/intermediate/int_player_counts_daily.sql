-- One row per game and UTC day: how many players the measurements of that
-- day showed. With a measurement every half hour a full day has 48 samples;
-- `samples` says how much of the day the numbers really cover.
select
    appid,
    cast(measured_at as date) as day,
    count(*) as samples,
    min(player_count) as players_min,
    max(player_count) as players_max,
    cast(round(avg(player_count)) as bigint) as players_avg,
    min(measured_at) as first_measured_at,
    max(measured_at) as last_measured_at
from {{ ref('stg_player_counts') }}
group by 1, 2
