select distinct
    region_code,
    region_name
from {{ ref('stg_stations') }}
where region_code is not null
