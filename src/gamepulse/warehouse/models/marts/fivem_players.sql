-- One row per read of FiveM's own player count, per source file.
select source_url, measured_at, players
from {{ ref('stg_fivem_counts') }}
