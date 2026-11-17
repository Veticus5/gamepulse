-- One row per game and day with a known Steam price; the agent's evidence
-- for discounts.
select * from {{ ref('int_prices_daily') }}
