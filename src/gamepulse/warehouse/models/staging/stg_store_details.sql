{{ config(materialized='view') }}

-- One row per game: what the Steam store said about it at the latest fetch.
with source as (
    select *
    from {{ read_jsonl(var("raw_dir") ~ "/appdetails/*.jsonl", {
        "appid": "BIGINT",
        "fetched_at": "VARCHAR",
        "details": "STRUCT(header_image VARCHAR, developers VARCHAR[], publishers VARCHAR[], release_date STRUCT(date VARCHAR), genres STRUCT(description VARCHAR)[], is_free BOOLEAN, short_description VARCHAR)"
    }) }}
)

select
    appid,
    details.header_image as header_image,
    coalesce(details.developers, []) as developers,
    coalesce(details.publishers, []) as publishers,
    details.release_date.date as release_date_text,
    coalesce(list_filter(list_transform(details.genres, lambda g: g.description), lambda d: d is not null), []) as genres,
    details.is_free as is_free,
    details.short_description as short_description,
    {{ utc_timestamp('fetched_at') }} as fetched_at
from source
where appid is not null
  and details is not null
qualify row_number() over (partition by appid order by {{ utc_timestamp('fetched_at') }} desc nulls last, line_no desc) = 1
