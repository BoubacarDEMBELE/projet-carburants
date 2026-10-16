select
    station_id,
    address,
    city,
    postcode,
    department_code,
    department_name,
    region_code,
    latitude,
    longitude,
    last_seen_on
from {{ ref('stg_stations') }}
