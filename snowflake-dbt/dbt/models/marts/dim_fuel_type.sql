select
    fuel_code,
    fuel_label,
    fuel_family
from {{ ref('fuel_types') }}
