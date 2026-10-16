-- One-time Snowflake setup — run in a worksheet as ACCOUNTADMIN.
-- Least privilege: a dedicated role + service user; an XS warehouse that suspends after 60 s.

use role accountadmin;

-- Compute: smallest size, auto-suspend to protect the trial credits
create warehouse if not exists fuel_wh
  warehouse_size = 'XSMALL'
  auto_suspend = 60
  auto_resume = true
  initially_suspended = true;

-- Storage
create database if not exists fuel_db;
create schema if not exists fuel_db.raw;        -- landed by Python, untouched
create schema if not exists fuel_db.analytics;  -- built by dbt

-- Access
create role if not exists transformer;
grant usage on warehouse fuel_wh to role transformer;
grant usage, create schema on database fuel_db to role transformer;
grant all on schema fuel_db.raw to role transformer;
grant all on schema fuel_db.analytics to role transformer;
grant all on future tables in schema fuel_db.raw to role transformer;
grant all on future tables in schema fuel_db.analytics to role transformer;
grant all on future views in schema fuel_db.analytics to role transformer;

-- Service user for ingestion + dbt: key-pair authentication (no password).
-- TYPE = SERVICE: Snowflake no longer accepts password-only sign-in for new users.
-- The public key below is not a secret; the private key stays on the owner's PC and in a GitHub secret.
create user if not exists fuel_svc
  type = service
  rsa_public_key = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArNOvj1qW3aLqGI69KWGMQ5SkKfQYxekpFc60m5WM2clU3DqgFcocq33wgnj93p2uPRSsg1nGTAABN4/chKARjYt3LMesYAlChPPigGaQnEaVhYz7r13vylCBYPDgQHfoxFj1xCpR9vVu/PUIsMRyOv2sTOK6u3U/MQAGu+jglQGngliR2Y8hwu6lTd+0D8bEf7Zd0nRm5qbbrmnVt7J+jAPxA+3xs0CqBs0EafmAq0PPyAngreCYyk2GmurfcpxDizt1illEv090nJ31fJ7TuBbsPcccMpyQ6FRBnmeFDksBrSTMn0JcwWYdhjotzfgqCU5bgQKUHLOz/y6c2p8kfwIDAQAB'
  default_role = transformer
  default_warehouse = fuel_wh;
grant role transformer to user fuel_svc;
grant role transformer to role sysadmin;

-- RAW landing table: one JSON record per station per run
create table if not exists fuel_db.raw.fuel_prices_raw (
  payload    variant       not null,
  run_date   date          not null,
  loaded_at  timestamp_ntz not null default current_timestamp()
);

-- Cost guard: stop the warehouse if the month goes over 10 credits
create or replace resource monitor fuel_monitor with credit_quota = 10
  frequency = monthly start_timestamp = immediately
  triggers on 90 percent do suspend;
alter warehouse fuel_wh set resource_monitor = fuel_monitor;
