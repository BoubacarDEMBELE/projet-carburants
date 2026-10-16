-- Grain: one row per station x fuel x day. Incremental: only new days are processed.
{{ config(materialized='incremental', unique_key=['station_id', 'fuel_code', 'date_day']) }}

select
    station_id,
    fuel_code,
    region_code,
    date_day,
    price_eur_per_litre,
    price_change_vs_previous
from {{ ref('int_prices_enriched') }}
{% if is_incremental() %}
where date_day > (select max(date_day) from {{ this }})
{% endif %}
