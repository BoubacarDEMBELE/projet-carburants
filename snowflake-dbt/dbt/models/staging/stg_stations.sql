-- Latest known attributes of each station.
-- Postcodes stay strings ("01234"); coordinates come from geom (the "latitude" field is in degrees x 100000).
with raw as (
    select payload, run_date
    from {{ source('raw', 'fuel_prices_raw') }}
)

select
    payload:id::string                         as station_id,
    initcap(payload:adresse::string)           as address,
    initcap(payload:ville::string)             as city,
    lpad(payload:cp::string, 5, '0')           as postcode,
    payload:code_departement::string           as department_code,
    payload:departement::string                as department_name,
    payload:code_region::string                as region_code,
    payload:region::string                     as region_name,
    payload:geom:lat::float                    as latitude,
    payload:geom:lon::float                    as longitude,
    run_date                                   as last_seen_on
from raw
qualify row_number() over (partition by payload:id::string order by run_date desc) = 1
