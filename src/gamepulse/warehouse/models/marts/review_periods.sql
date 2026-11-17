-- One row per game and period (day, week or month) with its review counts;
-- what the review chart draws. Days come from every stored snapshot, weeks
-- and months from the latest one.
select appid, grain, period_start, period_end, positive, negative, reviews, share_positive, is_complete
from {{ ref('int_review_periods') }}
