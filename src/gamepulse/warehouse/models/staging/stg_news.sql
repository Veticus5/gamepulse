{{ config(materialized='view') }}

-- One row per news item Steam lists for a game, in the version stored last.
-- feed_type 1 is the developer's own post, 0 an article from the press.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/news/*.jsonl", {
        "gid": "VARCHAR", "appid": "BIGINT", "title": "VARCHAR", "url": "VARCHAR",
        "is_external_url": "BOOLEAN", "author": "VARCHAR", "contents": "VARCHAR",
        "feedlabel": "VARCHAR", "feedname": "VARCHAR", "feed_type": "BIGINT",
        "date": "BIGINT", "tags": "VARCHAR[]", "fetched_at": "VARCHAR"
    }) }}
)

select
    gid,
    appid,
    title,
    url,
    author,
    contents,
    feedlabel as feed_label,
    feedname as feed_name,
    feed_type,
    feed_type = 1 as is_official,
    coalesce(tags, []) as tags,
    cast(to_timestamp("date") at time zone 'UTC' as timestamp) as published_at,
    {{ utc_timestamp('fetched_at') }} as fetched_at
from source
where gid is not null
  and appid is not null
  and "date" is not null
qualify row_number() over (partition by gid order by fetched_at desc nulls last) = 1
