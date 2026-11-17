-- One row per episode, with the agent's latest explanation when there is
-- one. `verdict` is NULL for an episode nobody has explained yet.
select
    e.*,
    x.verdict,
    x.summary,
    x.missing,
    x.hypotheses,
    x.evidence,
    x.reviews_collected,
    x.dropped,
    x.model as explained_by_model,
    x.prompt_version,
    x.answered_by,
    x.explained_at,
    x.episode_id is not null as is_explained
from {{ ref('anomaly_episodes') }} as e
left join {{ ref('explanations') }} as x using (episode_id)
