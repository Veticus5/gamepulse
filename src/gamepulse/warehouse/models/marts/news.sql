-- One row per news item of a tracked game, with the classifier's label when
-- there is one. The label columns are model output; everything else is what
-- Steam returned.
select
    n.gid,
    n.appid,
    n.title,
    n.url,
    n.author,
    n.feed_label,
    n.feed_name,
    n.is_official,
    n.tags,
    n.published_at,
    n.contents,
    e.event_type,
    e.effective_date,
    e.summary as label_summary,
    e.importance,
    e.confidence as label_confidence,
    e.model as label_model,
    e.prompt_version as label_prompt_version,
    e.classified_at,
    e.gid is not null as is_labelled
from {{ ref('stg_news') }} as n
left join {{ ref('stg_news_events') }} as e using (gid)
