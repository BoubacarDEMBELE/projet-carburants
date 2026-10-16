-- Calendar from the first ingestion day to one year ahead.
with days as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2026-10-01' as date)",
        end_date="dateadd(year, 1, current_date())"
    ) }}
)

select
    cast(date_day as date)                     as date_day,
    year(date_day)                             as year,
    month(date_day)                            as month,
    monthname(date_day)                        as month_name,
    weekofyear(date_day)                       as iso_week,
    dayofweekiso(date_day)                     as day_of_week,
    dayofweekiso(date_day) in (6, 7)           as is_weekend
from days
