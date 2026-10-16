-- Singular test: any row returned is a failure.
-- A pump price outside 0.50–4.00 EUR/L is almost certainly a data-entry error at the station.
select *
from {{ ref('fct_fuel_prices') }}
where price_eur_per_litre not between 0.5 and 4.0
