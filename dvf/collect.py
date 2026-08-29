"""Projet 4 — Valeurs foncières (DVF) : le nettoyage de données réelles.

    python dvf/collect.py
    python dvf/collect.py --dry-run          # sans écrire en base

La plomberie est identique aux projets 2 et 3 : extract / transform / load.
Ce qui change ici, et qui fait TOUT l'intérêt du projet, c'est transform() :
la donnée brute est sale, et chaque règle de nettoyage doit être justifiée.
"""

import argparse
import gzip
import io
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("dvf")

# --- CONFIGURATION ---
DEPARTEMENT = "78"
CODE_COMMUNE = "78551"          # Saint-Germain-en-Laye
ANNEES = [2021, 2022, 2023, 2024, 2025]
URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{dep}.csv.gz"

# On ne lit que 11 colonnes sur 40 : divise par ~4 la mémoire utilisée.
COLONNES = ["id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere",
            "adresse_nom_voie", "code_postal", "code_commune", "nom_commune",
            "type_local", "surface_reelle_bati", "nombre_pieces_principales"]

# Sans ce forçage, pandas convertit "78551" en entier 78551 et "01234" en 1234.
# Un code INSEE est un IDENTIFIANT, pas un nombre.
DTYPES = {"code_commune": str, "code_postal": str, "adresse_nom_voie": str}


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------
def extract() -> pd.DataFrame:
    """Télécharge les fichiers annuels et ne garde que la commune cible."""
    morceaux = []
    for annee in ANNEES:
        url = URL.format(annee=annee, dep=DEPARTEMENT)
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        # On décompresse en mémoire : inutile d'écrire 2 Mo sur le disque.
        with gzip.open(io.BytesIO(r.content), "rb") as f:
            df = pd.read_csv(f, usecols=COLONNES, dtype=DTYPES)
        # Filtrage commune AU PLUS TOT : on porte 10 000 lignes au lieu de 294 000.
        df = df[df.code_commune == CODE_COMMUNE]
        logger.info("%s : %d ventes sur la commune", annee, len(df))
        morceaux.append(df)
    return pd.concat(morceaux, ignore_index=True)


# ---------------------------------------------------------------------------
# TRANSFORM — le cœur du projet
# ---------------------------------------------------------------------------
def transform(brut: pd.DataFrame) -> pd.DataFrame:
    """Applique les règles de nettoyage, en journalisant ce que chacune retire.

    Journaliser l'entonnoir n'est pas cosmétique : c'est ce qui permet de
    détecter qu'une règle est devenue trop agressive après un changement de
    la source. Une règle qui se met à retirer 90 % des lignes est un signal.
    """
    etapes = [("lignes brutes", len(brut))]
    d = brut

    # 1. Ne garder que les vraies ventes.
    #    Les échanges, expropriations et adjudications ont des prix qui ne
    #    reflètent pas le marché.
    d = d[d.nature_mutation == "Vente"]
    etapes.append(("nature_mutation = Vente", len(d)))

    # 2. Ne garder que les logements.
    #    C'est la règle qui retire le plus : caves, parkings, terrains et
    #    dépendances n'ont pas de prix au m² habitable. Ce n'est PAS une perte,
    #    c'est la définition du périmètre.
    d = d[d.type_local.isin(["Appartement", "Maison"])]
    etapes.append(("type_local = Appartement/Maison", len(d)))

    # 3. Écarter les lignes inexploitables.
    d = d[d.valeur_fonciere.notna() & (d.valeur_fonciere > 0)]
    d = d[d.surface_reelle_bati.notna() & (d.surface_reelle_bati > 0)]
    etapes.append(("prix et surface renseignes", len(d)))

    # 4. LE PIEGE DES VENTES MULTI-LOTS.
    #
    #    Une même vente (id_mutation) peut couvrir plusieurs lignes : un
    #    appartement + une cave + un parking, ou deux logements vendus ensemble.
    #    Sur CHAQUE ligne, `valeur_fonciere` porte le prix TOTAL de la vente,
    #    répété à l'identique — vérifié : 187 mutations sur 187 dans ce jeu.
    #
    #    Sans agrégation, une vente à 500 000 EUR étalée sur 3 lignes compte
    #    trois fois et gonfle toutes les statistiques. Sommer les prix serait
    #    encore pire : on obtiendrait 1 500 000 EUR.
    #
    #    La bonne opération : une ligne par mutation, surfaces SOMMEES,
    #    prix pris UNE SEULE FOIS.
    d = d.groupby("id_mutation").agg(
        date_mutation=("date_mutation", "first"),
        valeur_fonciere=("valeur_fonciere", "first"),   # first, jamais sum
        surface=("surface_reelle_bati", "sum"),         # sum, jamais first
        voie=("adresse_nom_voie", "first"),
        code_postal=("code_postal", "first"),
        nom_commune=("nom_commune", "first"),
        type_local=("type_local", "first"),
        nb_pieces=("nombre_pieces_principales", "sum"),
        nb_lots=("id_mutation", "size"),
    ).reset_index()
    etapes.append(("1 ligne = 1 mutation", len(d)))

    d["prix_m2"] = d.valeur_fonciere / d.surface
    d["annee"] = pd.to_datetime(d.date_mutation).dt.year

    # 5. Les valeurs aberrantes.
    #    Sur ce jeu, le brut va de 0 à 103 472 EUR/m2. Sans écrêtage, aucune
    #    moyenne n'a de sens. On coupe aux percentiles plutôt qu'à des seuils
    #    en dur : la règle reste valable si on change de commune.
    bas, haut = d.prix_m2.quantile([0.01, 0.99])
    d = d[(d.prix_m2 >= bas) & (d.prix_m2 <= haut)]
    etapes.append((f"ecretage 1%-99% ({bas:.0f}-{haut:.0f} EUR/m2)", len(d)))

    # 6. Normalisation du nom de voie.
    #    DVF écrit les voies en majuscules sans accents, mais l'espacement
    #    varie. On uniformise pour pouvoir regrouper par rue.
    d["voie"] = d.voie.str.strip().str.replace(r"\s+", " ", regex=True)

    # Journal de l'entonnoir
    logger.info("--- entonnoir de nettoyage ---")
    prec = etapes[0][1]
    for nom, n in etapes:
        logger.info("  %-42s %6d  (%+d)", nom, n, n - prec)
        prec = n
    logger.info("  conserve : %.0f %% des lignes brutes", 100 * len(d) / len(brut))

    # Garde-fou : si le nettoyage ne laisse presque rien, quelque chose a changé.
    if len(d) < 0.05 * len(brut):
        logger.error("Moins de 5 %% des lignes survivent : la source a change ?")
        sys.exit(1)

    return d


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
_UPSERT = text("""
    insert into dvf_vente (id_mutation, date_mutation, annee, code_commune,
                           nom_commune, code_postal, voie, type_local,
                           nb_lots, nb_pieces, surface, valeur_fonciere, prix_m2)
    values (:id_mutation, :date_mutation, :annee, :code_commune,
            :nom_commune, :code_postal, :voie, :type_local,
            :nb_lots, :nb_pieces, :surface, :valeur_fonciere, :prix_m2)
    on conflict (id_mutation) do update set
        valeur_fonciere = excluded.valeur_fonciere,
        surface         = excluded.surface,
        prix_m2         = excluded.prix_m2,
        voie            = excluded.voie,
        collecte_le     = now()
""")


def load(df: pd.DataFrame) -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    df = df.assign(code_commune=CODE_COMMUNE)
    cols = ["id_mutation", "date_mutation", "annee", "code_commune", "nom_commune",
            "code_postal", "voie", "type_local", "nb_lots", "nb_pieces",
            "surface", "valeur_fonciere", "prix_m2"]
    # psycopg2 ne comprend pas les NaN de pandas.
    lignes = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records")
    with engine.begin() as conn:
        conn.execute(_UPSERT, lignes)
    logger.info("Base a jour : %d ventes", len(lignes))


def archive(df: pd.DataFrame) -> Path:
    """Archive le jeu NETTOYE, pas le brut.

    Le brut est re-telechargeable a tout moment depuis data.gouv.fr et pese
    9 Mo. Le jeu nettoye pese quelques dizaines de Ko et incorpore toutes les
    regles de nettoyage : c'est lui qui est couteux a reproduire.

    Regle generale : on archive ce qui est cher a refabriquer, pas ce qui est
    gratuit a retelecharger.
    """
    dossier = Path("data/dvf")
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{date.today():%Y-%m-%d}.csv.gz"
    df.to_csv(chemin, index=False, compression={"method": "gzip", "mtime": 0})
    logger.info("Archive : %s (%d octets)", chemin, chemin.stat().st_size)
    return chemin


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Collecte DVF")
    parser.add_argument("--dry-run", action="store_true", help="ne pas ecrire en base")
    args = parser.parse_args()

    try:
        brut = extract()
        propre = transform(brut)
        archive(propre)

        if args.dry_run:
            logger.info("Mode --dry-run : pas d'ecriture en base")
            apercu = (propre.groupby("annee")
                      .agg(ventes=("prix_m2", "size"), median=("prix_m2", "median"))
                      .round(0))
            print(apercu.to_string())
        else:
            load(propre)
    except requests.RequestException as e:
        logger.error("Telechargement en echec : %s", e)
        return 1
    except Exception:
        logger.exception("Echec de la collecte")
        return 1

    logger.info("Collecte terminee")
    return 0


if __name__ == "__main__":
    sys.exit(main())
