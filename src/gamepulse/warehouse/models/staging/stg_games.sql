{{ config(materialized='view') }}

-- One row per tracked game. The list is the project's own configuration
-- (games.toml), written next to the other inputs before each build.
with source as (
    select *
    from {{ read_jsonl(var("derived_dir") ~ "/games.jsonl", {"appid": "BIGINT", "name": "VARCHAR"}) }}
)

select appid, name
from source
where appid is not null
qualify row_number() over (partition by appid order by name) = 1
