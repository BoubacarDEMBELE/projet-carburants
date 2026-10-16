# Fuel Price Analytics — Snowflake · dbt · BI

End-to-end modern data stack — **automated ingestion → Snowflake → dbt (staging → marts, tests, docs) → BI dashboard** —
monitoring fuel-price competitiveness and volatility across French regions.

> Source: [Prix des carburants en France — flux instantané](https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/)
> (French Ministry of Economy, open data, ~9,800 stations, no API key).

## Architecture

```
Open-data API  ──►  Python ingestion  ──►  Snowflake RAW (VARIANT, 1 row / station / run)
                                                │
                                          dbt transform
                     staging (views) ─► intermediate ─► marts (star schema, tables)
                                                │
                                   Power BI / Looker Studio dashboard
Orchestration: GitHub Actions — daily ingest + dbt build
```

## What this project demonstrates

| Skill | Where |
|---|---|
| Semi-structured data in Snowflake (`VARIANT`, JSON paths) | `models/staging/stg_fuel_prices.sql` |
| Wide → long reshaping in SQL | `models/staging/stg_fuel_prices.sql` |
| Layered dbt project (staging / intermediate / marts) | `dbt/models/` |
| Dimensional modeling (star schema) | `dbt/models/marts/` |
| Incremental fact table | `fct_fuel_prices.sql` |
| Data tests (unique, not_null, relationships, accepted_values, singular) | `_staging.yml`, `_marts.yml`, `tests/` |
| Documentation site | `dbt docs generate` |
| CI/CD orchestration | `../.github/workflows/snowflake_dbt_daily.yml` |
| Least-privilege Snowflake setup, key-pair service user, cost control (XS warehouse, auto-suspend, resource monitor) | `snowflake/setup.sql` |

## Star schema

`fct_fuel_prices` — grain: **one row per station × fuel type × day**

| Dimension | Key |
|---|---|
| `dim_station` | `station_id` |
| `dim_fuel_type` | `fuel_code` |
| `dim_region` | `region_code` |
| `dim_date` | `date_day` |

## Dashboard (analyst / finance angle)

- Average price by fuel / region over time
- Min–max spread by region (competitiveness)
- Week-over-week and month-over-month change
- Cheapest / most expensive stations, volatility indicator

*(screenshots to come)*

## Run it yourself

1. `snowflake/setup.sql` — run once in a Snowflake worksheet (as ACCOUNTADMIN).
2. Copy `.env.example` to `.env` and fill it in (never commit `.env` or the private key).
3. `pip install -r ingestion/requirements.txt` then `python ingestion/load_fuel_prices.py`
4. `cd dbt && dbt deps && dbt build --profiles-dir .` (copy `profiles.example.yml` to `profiles.yml` first)
5. `dbt docs generate && dbt docs serve`

## Repository structure

```
(workflow: ../.github/workflows/snowflake_dbt_daily.yml — daily ingestion + dbt build)
├── snowflake/setup.sql              warehouse, database, schemas, role, user
├── ingestion/
│   ├── load_fuel_prices.py          API → Snowflake RAW
│   └── requirements.txt
└── dbt/
    ├── dbt_project.yml
    ├── profiles.example.yml         Snowflake connection via env vars (no secrets)
    ├── packages.yml                 dbt_utils
    ├── seeds/fuel_types.csv
    ├── models/staging/              stg_fuel_prices, stg_stations
    ├── models/intermediate/         int_prices_enriched
    ├── models/marts/                dim_station, dim_date, dim_fuel_type, dim_region, fct_fuel_prices
    └── tests/                       assert_price_in_realistic_range.sql
```
