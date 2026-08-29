import os
import sys
import gzip
import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import create_engine, text
from urllib3.util.retry import Retry

# --- CONFIGURATION ---
DATASET = "regularite-mensuelle-tgv-aqst"
BASE = f"https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/{DATASET}"

# On utilise /exports/json et NON /records.
#
# L'endpoint /records plafonne à offset + limit <= 10000 : au-delà il renvoie
# un 400. Le dataset comptant 12 544 lignes, une pagination classique en
# récupérait 10 000 et s'arrêtait — soit 20 % des données manquantes, SANS
# erreur explicite. Le seul signal était le chiffre rond.
#
# /exports/json n'a pas de plafond et renvoie tout en un appel.
EXPORT_URL = f"{BASE}/exports/json"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("La variable d'environnement DATABASE_URL est manquante.")


# --- 1. RÉSILIENCE RÉSEAU ---
def get_resilient_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


# --- 2. EXTRACTION ---
def fetch_sncf_data():
    print("Début de la collecte API SNCF...")
    session = get_resilient_session()
    r = session.get(EXPORT_URL, timeout=180)   # export complet : prévoir large
    r.raise_for_status()
    records = r.json()
    print(f"Extraction terminée : {len(records)} enregistrements récupérés.")
    return records


raw_records = fetch_sncf_data()

if not raw_records:
    # sys.exit(1) et non exit() : sinon le run s'affiche en vert.
    print("ERREUR : aucune donnée récupérée.")
    sys.exit(1)


# --- 3. RAW LAYER : archive compressée dans Git, pas dans Postgres ---
#
# La version précédente insérait une ligne JSONB par enregistrement, soit
# 12 544 lignes à chaque exécution, sans clé d'unicité : chaque relance
# empilait un jeu complet. Sur un Free Tier de 500 Mo, c'est intenable.
#
# Même architecture chaud/froid que le pipeline carburants :
#   Postgres = la table structurée, requêtable
#   Git      = le brut compressé, pour rejouer un parsing a posteriori
RAW_DIR = Path("data/sncf_raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)
raw_path = RAW_DIR / f"{date.today():%Y-%m-%d}.json.gz"
with gzip.open(raw_path, "wt", encoding="utf-8") as f:
    json.dump(raw_records, f, ensure_ascii=False)
print(f"Archive brute : {raw_path} ({raw_path.stat().st_size} octets)")


# --- 4. PARSING & TRANSFORMATION ---
#
# Noms de champs vérifiés directement sur l'API le 29/08/2026.
# Le nom d'un champ n'est jamais une hypothèse : on lit une vraie ligne avant.
parsed_list = []
for item in raw_records:
    date_str = item.get("date")             # format "2018-01"
    depart = item.get("gare_depart")
    arrivee = item.get("gare_arrivee")

    if not date_str or not depart or not arrivee:
        continue

    prevu = item.get("nb_train_prevu")
    annule = item.get("nb_annulation")
    # `nombre_en_service` n'existe pas dans la source : on le dérive.
    circules = (prevu - annule) if (prevu is not None and annule is not None) else None

    id_liaison_mois = f"{date_str}_{depart}_{arrivee}".replace(" ", "_")

    parsed_list.append({
        "id_liaison_mois": id_liaison_mois,
        "annee_mois": str(date_str),
        "axe": item.get("service"),          # "National" / "International"
        "depart": depart,
        "arrivee": arrivee,
        "nombre_programmes": prevu,
        "nombre_circules": circules,
        "nombre_annules": annule,
        "nombre_retard_arrivee": item.get("nb_train_retard_arrivee"),
        "retard_moyen_tous_trains": item.get("retard_moyen_tous_trains_arrivee"),
        "retard_moyen_trains_en_retard": item.get("retard_moyen_arrivee"),
        # Les 6 causes totalisent 100 %. En omettre une fausse silencieusement
        # toute répartition : avec 5 causes sur 6, la somme tombe à ~95 %.
        "cause_externe_pct": item.get("prct_cause_externe"),
        "cause_infrastructure_pct": item.get("prct_cause_infra"),
        "cause_materiel_pct": item.get("prct_cause_materiel_roulant"),
        "cause_exploitation_pct": item.get("prct_cause_gestion_trafic"),
        "cause_gestion_gare_pct": item.get("prct_cause_gestion_gare"),
        "cause_voyageurs_pct": item.get("prct_cause_prise_en_charge_voyageurs"),
    })

if not parsed_list:
    print("ERREUR : aucun enregistrement n'a pu être parsé.")
    sys.exit(1)

df_clean = pd.DataFrame(parsed_list).drop_duplicates(subset=["id_liaison_mois"])

# Contrôle qualité : la somme des causes doit valoir ~100 % quand elle est
# renseignée. Si ce n'est pas le cas, un champ a changé de nom côté source.
causes = [c for c in df_clean.columns if c.endswith("_pct")]
somme = df_clean[causes].sum(axis=1)
verifiables = somme[somme > 0]
hors_norme = ((verifiables < 99) | (verifiables > 101)).sum()
print(f"Contrôle causes : {len(verifiables)} lignes vérifiables, {hors_norme} hors norme")
if len(verifiables) and hors_norme / len(verifiables) > 0.05:
    print("ERREUR : la somme des causes dévie. Un champ a probablement changé.")
    sys.exit(1)

# psycopg2 ne comprend pas les NaN/NaT de pandas.
df_clean = df_clean.astype(object).where(df_clean.notna(), None)


# --- 5. INGESTION STRUCTURÉE (UPSERT) ---
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    print(f"Ingestion de {len(df_clean)} lignes transformées...")
    sql_upsert = text("""
        INSERT INTO sncf_regularite (
            id_liaison_mois, annee_mois, axe, depart, arrivee,
            nombre_programmes, nombre_circules, nombre_annules, nombre_retard_arrivee,
            retard_moyen_tous_trains, retard_moyen_trains_en_retard,
            cause_externe_pct, cause_infrastructure_pct, cause_materiel_pct,
            cause_exploitation_pct, cause_gestion_gare_pct, cause_voyageurs_pct
        )
        VALUES (
            :id_liaison_mois, :annee_mois, :axe, :depart, :arrivee,
            :nombre_programmes, :nombre_circules, :nombre_annules, :nombre_retard_arrivee,
            :retard_moyen_tous_trains, :retard_moyen_trains_en_retard,
            :cause_externe_pct, :cause_infrastructure_pct, :cause_materiel_pct,
            :cause_exploitation_pct, :cause_gestion_gare_pct, :cause_voyageurs_pct
        )
        ON CONFLICT (id_liaison_mois) DO UPDATE SET
            nombre_programmes             = EXCLUDED.nombre_programmes,
            nombre_circules               = EXCLUDED.nombre_circules,
            nombre_annules                = EXCLUDED.nombre_annules,
            nombre_retard_arrivee         = EXCLUDED.nombre_retard_arrivee,
            retard_moyen_tous_trains      = EXCLUDED.retard_moyen_tous_trains,
            retard_moyen_trains_en_retard = EXCLUDED.retard_moyen_trains_en_retard,
            cause_externe_pct             = EXCLUDED.cause_externe_pct,
            cause_infrastructure_pct      = EXCLUDED.cause_infrastructure_pct,
            cause_materiel_pct            = EXCLUDED.cause_materiel_pct,
            cause_exploitation_pct        = EXCLUDED.cause_exploitation_pct,
            cause_gestion_gare_pct        = EXCLUDED.cause_gestion_gare_pct,
            cause_voyageurs_pct           = EXCLUDED.cause_voyageurs_pct;
    """)
    conn.execute(sql_upsert, df_clean.to_dict(orient="records"))

print("Succès ! Ingestion brute et transformée terminée.")
