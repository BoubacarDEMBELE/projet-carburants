# Prix des carburants — pipeline ETL serverless

![Collecte quotidienne](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/daily_pipeline.yml/badge.svg)

Collecte automatique, chaque matin, du prix des carburants autour d'un point donné.
Historisation en PostgreSQL. **Aucun serveur, aucun coût d'infrastructure.**

> **La question de départ** : quelle est la station la moins chère autour de chez moi,
> et combien l'écart avec la plus chère pèse-t-il sur un plein ?

---

## Architecture

```
API data.economie.gouv.fr
        │  extraction — pagination par offset
        ▼
GitHub Actions (runner Ubuntu, éphémère, 6h UTC)
        │  transformation — Pandas, dédoublonnage
        ├──────────────► data/snapshots/AAAA-MM-JJ.csv.gz   (archive froide, Git)
        │  chargement — upsert vectorisé
        ▼
Supabase PostgreSQL (30 jours glissants, purge automatique)
```

Le runner est **détruit après chaque exécution**. Rien ne persiste sur la machine :
c'est la base qui porte la mémoire du projet. C'est ce qui rend le coût nul —
aucune machine ne tourne 24 h / 24.

### Rétention chaud / froid

| Couche | Contenu | Durée | Usage |
|---|---|---|---|
| PostgreSQL | 30 derniers jours, indexés | glissant | analyse rapide, requêtes SQL |
| Git (`data/snapshots/`) | historique complet, compressé | illimité | archive, rejeu, analyses longues |

La purge à 30 jours protège le quota Supabase (500 Mo en Free Tier). Sans l'archive
Git, tout ce qui dépasse 30 jours serait perdu **définitivement** : le flux de l'API
est un instantané, il n'a pas de mémoire et aucun rattrapage n'est possible.

L'archive est écrite à la granularité maximale (une ligne par station × carburant).
On peut toujours agréger plus tard ; on ne peut jamais désagréger.

---

## Source

[Prix des carburants en France — flux instantané](https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/),
publié par le ministère de l'Économie sous Licence Ouverte.
API REST sans clé, environ 9 800 stations au niveau national.

---

## Structure

```
├── .github/workflows/daily_pipeline.yml   cron quotidien + commit de l'archive
├── sql/schema.sql                         tables, index, vue, requêtes d'analyse
├── collect_carburants.py                  extraction, transformation, chargement
├── data/snapshots/                        archive froide (générée)
└── requirements.txt
```

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

Créer les tables : exécuter `sql/schema.sql` dans le SQL Editor de Supabase.

Puis définir la variable d'environnement :

```bash
export DATABASE_URL="postgresql+psycopg2://postgres.PROJECT_REF:MOT_DE_PASSE@aws-X-REGION.pooler.supabase.com:6543/postgres"
```

## Utilisation

```bash
python collect_carburants.py
```

## Mise en production

1. `Settings → Secrets and variables → Actions` → secret `DATABASE_URL`
2. `Settings → Actions → General → Workflow permissions` → **Read and write**
3. Onglet `Actions` → `Run workflow` pour un premier test manuel

---

## Décisions techniques

| Décision | Pourquoi |
|---|---|
| Clé primaire `(id_station, carburant, date_releve)` | Rend la collecte idempotente : trois exécutions le même jour produisent le même résultat qu'une seule. |
| Upsert vectorisé plutôt qu'une boucle d'insertion | Une seule requête au lieu d'un aller-retour réseau par ligne. Le coût est dans le réseau, pas dans le calcul. |
| Pooler transactionnel, port `6543` | Les runners GitHub Actions ne gèrent pas l'IPv6, or l'hôte direct Supabase n'est joignable qu'en IPv6. |
| Codes postaux en `text` | `"01234"` n'est pas `1234`. Un code postal est un identifiant, pas un nombre. |
| `geom.lat` / `geom.lon` plutôt que `latitude` / `longitude` | Les champs `latitude` et `longitude` de l'API sont des chaînes en degrés × 100000. `geom` porte les vraies coordonnées décimales. |
| Purge à 30 jours + archive Git | Tient le quota Free Tier sans jamais perdre d'historique. |
| `sys.exit(1)` si la collecte est vide | Sans code de retour non nul, un run sans donnée s'afficherait en vert et la journée perdue passerait inaperçue. |
| Commit quotidien de l'archive | Maintient le dépôt actif, ce qui empêche GitHub de désactiver le workflow planifié après 60 jours d'inactivité. |

---

## Pièges rencontrés

| Erreur | Cause réelle | Correctif |
|---|---|---|
| `Network is unreachable` | Les runners GitHub n'ont pas d'IPv6 vers l'hôte direct Supabase | Passer par le pooler IPv4, port `6543` |
| `tenant or user not found` | Sur le pooler, l'utilisateur doit porter la référence du projet | `postgres.PROJECT_REF`, et vérifier la région AWS |
| `password authentication failed` | Caractères réservés non encodés dans le mot de passe | Encoder en pourcentage `@` `:` `/` `?` `#` `[` `]` `%` `&` `+` — le point n'a jamais besoin de l'être |
| Exécution très lente | Un `execute()` par ligne dans une boucle Python | Un seul `execute()` avec `to_dict(orient="records")` |
| Un échec affiché en vert | Le script sortait avec le code 0 | `sys.exit(1)` sur le chemin d'erreur |

---

## Limites connues

- Le flux est un instantané : un prix modifié deux fois dans la même journée n'est vu qu'une fois.
- L'historique commence à la date du premier run. Aucun rattrapage sur le passé n'est possible.
- Le cron GitHub peut avoir plusieurs dizaines de minutes de retard ; l'heure exacte n'est pas garantie.
- `distance_km` est toujours `NULL` : l'API ne renvoie pas de champ `dist`. La distance devrait être calculée côté Python.
- Le périmètre est local (rayon autour d'un point). Le passage au national multiplierait le volume par ~70 et consommerait environ un quart du quota Supabase.
- L'API plafonne à `offset + limit <= 10000`. Avec 9 802 stations, une collecte nationale par pagination serait à 2 % du plafond : il faudrait passer par l'endpoint `/exports/json`, qui renvoie tout en un appel.

---

## Licence

Code sous licence MIT. Données sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
