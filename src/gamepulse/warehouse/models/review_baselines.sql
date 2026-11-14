-- Each finished period next to what was usual before it: the median over
-- the preceding periods (the period itself is not part of its own baseline).
-- Median and MAD are used instead of mean and standard deviation so that
-- one earlier review bomb does not hide the next one.
{% for grain, size in var('baseline_windows').items() %}
select
    p.*,
    count(*) over w as baseline_periods,
    median(share_positive) over w as baseline_share,
    mad(share_positive) over w as baseline_share_mad,
    median(reviews) over w as baseline_reviews,
    median(ln(reviews)) over w as baseline_ln_reviews,
    mad(ln(reviews)) over w as baseline_ln_reviews_mad
from {{ ref('review_periods') }} as p
where grain = '{{ grain }}' and is_complete and reviews > 0
window w as (
    partition by appid
    order by period_start
    rows between {{ size }} preceding and 1 preceding
)
{% if not loop.last %}union all{% endif %}
{% endfor %}
