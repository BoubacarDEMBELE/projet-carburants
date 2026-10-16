-- One row per station x fuel x run date.
-- The API is WIDE (one price column per fuel): we reshape it to LONG here.
with raw as (
    select payload, run_date
    from {{ source('raw', 'fuel_prices_raw') }}
),

fuels as (
    {% set fuels = ['gazole', 'sp95', 'sp98', 'e10', 'e85', 'gplc'] %}
    {% for f in fuels %}
    select
        payload:id::string                       as station_id,
        upper('{{ f }}')                         as fuel_code,
        payload:{{ f }}_prix::number(6, 3)       as price_eur_per_litre,
        -- ISO 8601 with offset ("2026-10-14T15:20:37+00:00"): parsed as UTC
        try_to_timestamp_tz(payload:{{ f }}_maj::string)::timestamp_ntz as source_updated_at,
        run_date
    from raw
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select *
from fuels
where price_eur_per_litre is not null   -- a station not selling a fuel is an absence, not missing data
qualify row_number() over (partition by station_id, fuel_code, run_date order by source_updated_at desc) = 1
