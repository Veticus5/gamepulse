-- One row per explained episode: the agent's latest answer. Kept apart from
-- the episodes so an answer is not lost when a rebuild redraws an episode.
select * from {{ ref('stg_explanations') }}
