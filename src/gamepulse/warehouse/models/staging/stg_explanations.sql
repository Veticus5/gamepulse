{{ config(materialized='view') }}

-- One row per episode the agent has explained: its latest explanation.
-- Hypotheses and evidence stay as JSON; their shape belongs to the agent.
with source as (
    select *
    from {{ read_jsonl(var("derived_dir") ~ "/explanations/*.jsonl", {
        "episode_id": "VARCHAR", "appid": "BIGINT", "input_hash": "VARCHAR", "prompt_version": "VARCHAR",
        "reviews_collected": "BIGINT", "verdict": "VARCHAR", "summary": "VARCHAR", "missing": "VARCHAR",
        "hypotheses": "JSON", "evidence": "JSON", "dropped": "JSON",
        "model": "VARCHAR", "source": "VARCHAR", "explained_at": "VARCHAR"
    }) }}
)

select
    episode_id,
    appid,
    verdict,
    summary,
    missing,
    hypotheses,
    evidence,
    dropped,
    coalesce(reviews_collected, 0) as reviews_collected,
    input_hash,
    prompt_version,
    model,
    source as answered_by,
    {{ utc_timestamp('explained_at') }} as explained_at
from source
where episode_id is not null
qualify row_number() over (partition by episode_id order by explained_at desc nulls last) = 1
