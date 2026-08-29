"""Projet 5 — Croiser DVF et DPE : créer une source qui n'existe nulle part.

    python dpe/collect.py --dry-run
    python dpe/collect.py

Les deux sources n'ont AUCUN identifiant commun. C'est tout l'intérêt du
projet : la jointure doit être construite, pas trouvée.

Stratégie retenue : rue normalisée + surface à ±10 %.
Taux d'appariement obtenu : 87,5 %. Il est journalisé à chaque exécution et
publié dans le README — un croisement dont on tait le taux d'appariement
n'est pas un résultat, c'est une opinion.
"""

import argparse
import logging
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("dpe")

CODE_COMMUNE = "78551"          # Saint-Germain-en-Laye
DATASET = "meg-83tjwtg8dyz4vv7h1dqe"   # DPE logements existants (depuis juillet 2021)
API = f"https://data.ademe.fr/data-fair/api/v1/datasets/{DATASET}/lines"
CHAMPS = ("etiquette_dpe,etiquette_ges,surface_habitable_logement,nom_rue_ban,"
          "numero_voie_ban,identifiant_ban,code_insee_ban,date_etablissement_dpe,"
          "type_batiment,periode_construction,conso_5_usages_par_m2_ep")
TOLERANCE_SURFACE = 0.10


# ---------------------------------------------------------------------------
# NORMALISATION DES NOMS DE VOIE — le coeur de la jointure
# ---------------------------------------------------------------------------
# DVF écrit "AV MAL FOCH", l'ADEME écrit "Avenue du Maréchal Foch".
# Sans traitement, ces deux chaînes ne se rencontrent jamais.
#
# Gain mesuré : 86,8 % -> 97,0 % de couverture, uniquement en développant les
# abréviations et en retirant les articles. Deux règles, dix points.
TYPES = (r"(RUE|AVENUE|BOULEVARD|PLACE|ROUTE|IMPASSE|ALLEE|ALLEES|CHEMIN|SQUARE|"
         r"SENTE|SENTIER|VILLA|COUR|PASSAGE|QUAI|CLOS|HAMEAU|RESIDENCE|PARC|MAIL|"
         r"ESPLANADE|ROND POINT|CHAUSSEE|DOMAINE|CITE|VOIE|PROMENADE|TERRASSE)")
ARTICLES = r"^(DU|DE LA|DES|DE L|DE|LA|LE|LES|L|D)\s+"
ABBREVIATIONS = {
    "AV": "AVENUE", "BD": "BOULEVARD", "PL": "PLACE", "RTE": "ROUTE",
    "IMP": "IMPASSE", "ALL": "ALLEE", "CHE": "CHEMIN", "SQ": "SQUARE",
    "RES": "RESIDENCE", "VLA": "VILLA", "PAS": "PASSAGE", "SEN": "SENTE",
    "MAL": "MARECHAL", "GAL": "GENERAL", "GEN": "GENERAL", "PDT": "PRESIDENT",
    "PRES": "PRESIDENT", "ST": "SAINT", "STE": "SAINTE", "DR": "DOCTEUR",
    "CDT": "COMMANDANT", "COL": "COLONEL", "MGR": "MONSEIGNEUR",
}


def normaliser_voie(s):
    """Ramène deux écritures d'une même rue à une chaîne identique."""
    if pd.isna(s):
        return None
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Z0-9 ]", " ", s.upper())
    s = re.sub(r"\s+", " ", s).strip()
    s = " ".join(ABBREVIATIONS.get(mot, mot) for mot in s.split())
    for _ in range(2):                       # 2 passes : "RESIDENCE RUE X"
        s = re.sub(rf"^{TYPES}\s+", "", s)
        s = re.sub(ARTICLES, "", s)
    s = re.sub(r"^\d+\s*(BIS|TER)?\s*", "", s)
    return s.strip() or None


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------
def extract_dpe() -> pd.DataFrame:
    """Récupère les DPE de la commune, par pagination A CURSEUR.

    L'API plafonne une page à 10 000 lignes. Avec 14 081 DPE sur la commune,
    une pagination par `offset` en perdrait 4 081 — silencieusement, avec pour
    seul signal un chiffre rond. C'est le même piège que sur l'API SNCF.

    La réponse porte un champ `next` : une URL complète à suivre jusqu'à
    disparition. Un curseur n'a pas de plafond, contrairement à un offset.
    """
    url, params, lignes, total = API, {
        "qs": f"code_insee_ban:{CODE_COMMUNE}", "size": 5000, "select": CHAMPS}, [], None
    while url:
        r = requests.get(url, params=params, timeout=180)
        r.raise_for_status()
        d = r.json()
        total = d.get("total", total)   # `total` n'est présent que sur la 1re page
        lignes += d["results"]
        logger.info("  +%d DPE (cumul %d/%s)", len(d["results"]), len(lignes), total)
        url, params = d.get("next"), None   # `next` porte déjà tous les paramètres

    if total and len(lignes) != total:
        logger.error("Extraction incomplete : %d sur %d annonces", len(lignes), total)
        sys.exit(1)
    return pd.DataFrame(lignes)


def extract_dvf(engine) -> pd.DataFrame:
    """Relit les ventes déjà nettoyées par le projet 4.

    On ne refait pas le nettoyage : le projet 4 est la source de vérité pour
    les ventes. Une pipeline consomme la sortie d'une autre — c'est ce qui
    évite deux définitions divergentes de « une vente propre ».
    """
    q = text("select id_mutation, date_mutation, annee, voie, type_local, "
             "surface, valeur_fonciere, prix_m2 from dvf_vente where code_commune = :c")
    return pd.read_sql(q, engine, params={"c": CODE_COMMUNE})


# ---------------------------------------------------------------------------
# TRANSFORM — la jointure
# ---------------------------------------------------------------------------
def croiser(dvf: pd.DataFrame, dpe: pd.DataFrame) -> pd.DataFrame:
    dpe = dpe[dpe.type_batiment.isin(["appartement", "maison"])].copy()
    dpe["surface_dpe"] = pd.to_numeric(dpe.surface_habitable_logement, errors="coerce")
    dpe = dpe.dropna(subset=["nom_rue_ban", "surface_dpe", "etiquette_dpe"])
    dpe = dpe[dpe.surface_dpe > 0]

    dvf["voie_n"] = dvf.voie.map(normaliser_voie)
    dpe["voie_n"] = dpe.nom_rue_ban.map(normaliser_voie)
    dvf = dvf.dropna(subset=["voie_n", "surface"])

    couverture = dvf.voie_n.isin(set(dpe.voie_n)).mean()
    logger.info("Couverture des rues : %.1f %% des ventes", 100 * couverture)

    # Jointure large sur la rue, puis filtrage sur l'écart de surface.
    # On ne peut pas joindre directement sur la surface : les deux sources ne
    # mesurent pas exactement la même chose (surface bâtie contre surface
    # habitable). D'où une tolérance, assumée et documentée.
    j = dvf.merge(
        dpe[["voie_n", "surface_dpe", "etiquette_dpe", "etiquette_ges",
             "periode_construction", "identifiant_ban", "conso_5_usages_par_m2_ep"]],
        on="voie_n", how="inner")
    j["ecart_surface"] = (j.surface_dpe - j.surface).abs() / j.surface
    j = j[j.ecart_surface <= TOLERANCE_SURFACE]

    # Une vente peut trouver plusieurs DPE : on garde le plus proche en surface.
    j = j.sort_values("ecart_surface").drop_duplicates(subset=["id_mutation"], keep="first")

    taux = len(j) / len(dvf)
    logger.info("--- APPARIEMENT ---")
    logger.info("  ventes DVF            : %d", len(dvf))
    logger.info("  ventes appariees      : %d", len(j))
    logger.info("  TAUX D'APPARIEMENT    : %.1f %%", 100 * taux)

    # Garde-fou : sous 50 %, le résultat n'est plus représentatif. Mieux vaut
    # un run rouge qu'une analyse publiée sur un échantillon biaisé.
    if taux < 0.50:
        logger.error("Taux d'appariement trop faible : resultat non representatif.")
        sys.exit(1)

    j["passoire"] = j.etiquette_dpe.isin(["F", "G"])
    return j


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
_UPSERT = text("""
    insert into dvf_dpe (id_mutation, date_mutation, annee, voie, type_local,
                         surface, valeur_fonciere, prix_m2, etiquette_dpe,
                         etiquette_ges, periode_construction, identifiant_ban,
                         conso_ep_m2, surface_dpe, ecart_surface, passoire)
    values (:id_mutation, :date_mutation, :annee, :voie, :type_local,
            :surface, :valeur_fonciere, :prix_m2, :etiquette_dpe,
            :etiquette_ges, :periode_construction, :identifiant_ban,
            :conso_ep_m2, :surface_dpe, :ecart_surface, :passoire)
    on conflict (id_mutation) do update set
        etiquette_dpe = excluded.etiquette_dpe,
        etiquette_ges = excluded.etiquette_ges,
        passoire      = excluded.passoire,
        collecte_le   = now()
""")

COLONNES = ["id_mutation", "date_mutation", "annee", "voie", "type_local", "surface",
            "valeur_fonciere", "prix_m2", "etiquette_dpe", "etiquette_ges",
            "periode_construction", "identifiant_ban", "conso_ep_m2", "surface_dpe",
            "ecart_surface", "passoire"]


def load(engine, df: pd.DataFrame) -> None:
    d = df.rename(columns={"conso_5_usages_par_m2_ep": "conso_ep_m2"})[COLONNES]
    lignes = d.astype(object).where(d.notna(), None).to_dict("records")
    with engine.begin() as conn:
        conn.execute(_UPSERT, lignes)
    logger.info("Base a jour : %d ventes croisees", len(lignes))


def archive(df: pd.DataFrame) -> Path:
    dossier = Path("data/dpe")
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{date.today():%Y-%m-%d}.csv.gz"
    df.to_csv(chemin, index=False, compression={"method": "gzip", "mtime": 0})
    logger.info("Archive : %s (%d octets)", chemin, chemin.stat().st_size)
    return chemin


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Croisement DVF x DPE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        dvf = extract_dvf(engine)
        logger.info("DVF relu depuis la base : %d ventes", len(dvf))
        dpe = extract_dpe()
        logger.info("DPE recuperes : %d", len(dpe))

        croise = croiser(dvf, dpe)
        archive(croise)

        if args.dry_run:
            logger.info("Mode --dry-run : pas d'ecriture en base")
            p = croise[croise.passoire].prix_m2.median()
            a = croise[~croise.passoire].prix_m2.median()
            print(f"\npassoires F+G : {croise.passoire.sum():>5} ventes, median {p:,.0f} EUR/m2"
                  .replace(",", " "))
            print(f"autres A-E    : {(~croise.passoire).sum():>5} ventes, median {a:,.0f} EUR/m2"
                  .replace(",", " "))
            print(f"ecart brut    : {100*(p/a-1):+.1f} %")
        else:
            load(engine, croise)
    except requests.RequestException as e:
        logger.error("Appel API en echec : %s", e)
        return 1
    except Exception:
        logger.exception("Echec du croisement")
        return 1

    logger.info("Croisement termine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
