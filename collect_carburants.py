import os
import requests
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text

# --- CONFIGURATION ---
LAT, LON, RAYON = 48.8566, 2.3522, "10km" 
URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("La variable d'environnement DATABASE_URL est manquante.")

# --- 1. COLLECTE API ---
def fetch_data():
    rows, offset = [], 0
    while True:
        params = {
            "where": f"distance(geom, GEOM'POINT({LON} {LAT})', {RAYON})",
            "limit": 100,
            "offset": offset,
        }
        r = requests.get(URL, params=params, timeout=30)
        r.raise_for_status()
        batch = r.json().get("results", [])
        rows += batch
        if len(batch) < 100:
            break
        offset += 100
    return rows

print("Récupération des données API...")
records = fetch_data()
print(f"{len(records)} stations trouvées dans la zone.")

if not records:
    print("Aucune donnée récupérée.")
    exit()

# --- 2. TRANSFORMATION DES DONNÉES ---
stations_list = []
prix_list = []
today = datetime.now().strftime("%Y-%m-%d")

for item in records:
    id_station = item.get("id")
    if not id_station:
        continue
    
    dist_m = item.get("dist")
    dist_km = round(dist_m / 1000, 2) if dist_m else None
    
    geom = item.get("geom") or {}
    lat = geom.get("lat")
    lon = geom.get("lon")

    # Table Station
    stations_list.append({
        "id_station": id_station,
        "adresse": item.get("adresse"),
        "ville": item.get("ville"),
        "cp": item.get("cp"),
        "latitude": lat,
        "longitude": lon,
        "distance_km": dist_km
    })

    # Table Prix
    carburants_map = {
        "Gazole": item.get("gazole_prix"),
        "SP95": item.get("sp95_prix"),
        "SP98": item.get("sp98_prix"),
        "E10": item.get("e10_prix"),
        "E85": item.get("e85_prix"),
        "GPLc": item.get("gplc_prix")
    }

    for carb_nom, prix_val in carburants_map.items():
        if prix_val is not None:
            prix_list.append({
                "id_station": id_station,
                "carburant": carb_nom,
                "prix": float(prix_val),
                "date_releve": today
            })

df_stations = pd.DataFrame(stations_list).drop_duplicates(subset=["id_station"])
df_prix = pd.DataFrame(prix_list).drop_duplicates(subset=["id_station", "carburant", "date_releve"])

# --- 3. INGESTION SQL (UPSERT VECTORISÉ + PURGE) ---
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    # 1. Upsert Stations en bloc (si non vide)
    if not df_stations.empty:
        sql_station = text("""
            INSERT INTO station (id_station, adresse, ville, cp, latitude, longitude, distance_km)
            VALUES (:id_station, :adresse, :ville, :cp, :latitude, :longitude, :distance_km)
            ON CONFLICT (id_station) DO UPDATE SET
                adresse = EXCLUDED.adresse,
                ville = EXCLUDED.ville,
                cp = EXCLUDED.cp,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                distance_km = EXCLUDED.distance_km;
        """)
        conn.execute(sql_station, df_stations.to_dict(orient="records"))

    # 2. Upsert Prix en bloc (si non vide)
    if not df_prix.empty:
        sql_prix = text("""
            INSERT INTO prix_carburant (id_station, carburant, prix, date_releve)
            VALUES (:id_station, :carburant, :prix, :date_releve)
            ON CONFLICT (id_station, carburant, date_releve) DO UPDATE SET
                prix = EXCLUDED.prix,
                collecte_le = NOW();
        """)
        conn.execute(sql_prix, df_prix.to_dict(orient="records"))

    # 3. Purge automatique des données de plus de 30 jours
    sql_cleanup = text("""
        DELETE FROM prix_carburant 
        WHERE date_releve::date < CURRENT_DATE - INTERVAL '30 days';
    """)
    conn.execute(sql_cleanup)

print("Insertion, mise à jour et nettoyage réussis dans Supabase !")