"""Daily ingestion: French fuel-price open-data API -> Snowflake RAW.

    python ingestion/load_fuel_prices.py            # full national load
    python ingestion/load_fuel_prices.py --dry-run  # fetch only, no Snowflake

Raw records are stored untouched as JSON (VARIANT): all cleaning and reshaping
happens in dbt, so the RAW layer can always be replayed.
Idempotent: today's rows are deleted before being re-inserted.
"""
import argparse
import json
import logging
import os
from datetime import date

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fuel")

API_URL = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
           "prix-des-carburants-en-france-flux-instantane-v2/records")
PAGE_SIZE = 100          # API maximum per call
MAX_OFFSET = 10_000      # API hard limit on offset: we split the country by department below


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=5, backoff_factor=1,
                                                      status_forcelist=[429, 500, 502, 503, 504])))
    return s


def _departments(session) -> list[str]:
    """Department codes present in the dataset (the offset cap forbids paging the whole country at once)."""
    r = session.get(API_URL, params={"select": "code_departement", "group_by": "code_departement", "limit": 200},
                    timeout=30)
    r.raise_for_status()
    # some stations have no department code: None is kept and queried with "is null"
    return [x["code_departement"] for x in r.json()["results"]]


def extract() -> list[dict]:
    session = _session()
    records: list[dict] = []
    for dep in _departments(session):
        filtre = "code_departement is null" if dep is None else f'code_departement="{dep}"'
        offset = 0
        while offset < MAX_OFFSET:
            r = session.get(API_URL, params={"where": filtre, "limit": PAGE_SIZE,
                                             "offset": offset}, timeout=30)
            r.raise_for_status()
            page = r.json()["results"]
            records.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    log.info("%d station records fetched", len(records))
    return records


def _credentials() -> dict:
    """Key-pair authentication (SNOWFLAKE_PRIVATE_KEY = PEM content), password only as a fallback."""
    pem = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    if not pem and os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH"):
        with open(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"], encoding="utf-8") as f:
            pem = f.read()
    if pem:
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        return {"private_key": der}
    return {"password": os.environ["SNOWFLAKE_PASSWORD"]}


def load(records: list[dict], run_date: date) -> None:
    import snowflake.connector  # imported here so --dry-run works without the driver

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.getenv("SNOWFLAKE_USER", "FUEL_SVC"),
        **_credentials(),
        role=os.getenv("SNOWFLAKE_ROLE", "TRANSFORMER"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "FUEL_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "FUEL_DB"),
        schema="RAW",
    )
    try:
        cur = conn.cursor()
        cur.execute("delete from fuel_prices_raw where run_date = %s", (run_date,))
        rows = [(json.dumps(rec, ensure_ascii=False), run_date) for rec in records]
        # PARSE_JSON cannot be used in a VALUES bind list: stage the text then convert
        cur.execute("create temporary table tmp_raw (payload_txt string, run_date date)")
        cur.executemany("insert into tmp_raw values (%s, %s)", rows)
        cur.execute("insert into fuel_prices_raw (payload, run_date) "
                    "select parse_json(payload_txt), run_date from tmp_raw")
        log.info("%d rows loaded into RAW.FUEL_PRICES_RAW for %s", len(rows), run_date)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    records = extract()
    if args.dry_run:
        log.info("dry run — sample record keys: %s", sorted(records[0])[:15] if records else "none")
        return
    load(records, date.today())


if __name__ == "__main__":
    main()
