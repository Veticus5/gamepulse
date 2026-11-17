-- One row per measurement of a game's player count; what the charts draw.
select appid, measured_at, player_count
from {{ ref('stg_player_counts') }}
