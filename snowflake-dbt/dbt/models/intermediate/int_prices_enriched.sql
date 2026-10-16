-- Prices joined to their station's geography, plus day-over-day change per station and fuel.
select
    p.station_id,
    p.fuel_code,
    p.run_date                                          as date_day,
    p.price_eur_per_litre,
    s.region_code,
    s.department_code,
    p.price_eur_per_litre
      - lag(p.price_eur_per_litre) over (partition by p.station_id, p.fuel_code order by p.run_date)
                                                        as price_change_vs_previous
from {{ ref('stg_fuel_prices') }} p
left join {{ ref('stg_stations') }} s using (station_id)
