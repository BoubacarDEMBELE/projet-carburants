# Pipelines de données publiques françaises

![Carburants](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/carburants_daily.yml/badge.svg)
![SNCF](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/sncf_monthly.yml/badge.svg)
![DVF](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/dvf_quarterly.yml/badge.svg)
![DPE](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/dpe_quarterly.yml/badge.svg)

Cinq pipelines sur des données ouvertes françaises, du plus simple au plus complet.
**Les cinq sont en production.**
Même méthode partout : **récupérer → héberger → nettoyer → croiser → publier**.

**Coût total d'infrastructure : 0 €.** Aucun serveur ne tourne.

---

## Les projets

| # | Projet | Compétence démontrée | État |
|---|---|---|---|
| 1 | Modélisation SQL | Schéma relationnel, index, contraintes, Postgres hébergé | ✅ |
| 2 | [Prix des carburants](carburants/) | Pipeline quotidienne, idempotence, cron, rétention chaud/froid | ✅ |
| 3 | [Régularité TGV](sncf/) | Consommation d'API, plafonds de pagination, contrôle qualité | ✅ |
| 4 | [Valeurs foncières (DVF)](dvf/) | Nettoyage de données réelles, dédoublonnage, valeurs aberrantes | ✅ |
| 5 | [DVF × DPE](dpe/) | Croisement de sources sans clé commune, jointure floue, variables de contrôle | ✅ |

---

## Le principe commun

```
Source ouverte (API ou CSV)
        │  extraction — pagination, retry, timeout
        ▼
GitHub Actions — runner éphémère, cron
        │  transformation — Pandas, typage, contrôles qualité
        ├──────────────► data/<projet>/   archive froide compressée, dans Git
        │  chargement — upsert idempotent
        ▼
Supabase PostgreSQL — couche chaude, requêtable
```

Le runner est **détruit après chaque exécution**. C'est ce qui rend le coût nul :
aucune machine ne tourne 24 h / 24. La mémoire du système est portée par la base
et par le dépôt, jamais par le serveur.

### Rétention chaud / froid

| Couche | Contenu | Durée |
|---|---|---|
| PostgreSQL | fenêtre récente, indexée | glissante |
| Git, `data/` | historique complet, compressé | illimitée |

La base reste sous le quota gratuit ; l'historique n'est jamais perdu.
L'archive est écrite à la **granularité maximale** : on peut toujours agréger
plus tard, jamais désagréger.

---

## Structure du dépôt

```
├── carburants/          projet 2 — collect.py, schema.sql, README
├── sncf/                projet 3 — collect.py, schema.sql, README
├── dvf/                 projet 4 — collect.py, schema.sql, README
├── dpe/                 projet 5 — collect.py, schema.sql, README
├── data/
│   ├── carburants/      archives quotidiennes (.csv.gz)
│   ├── sncf/            archives mensuelles (.json.gz)
│   ├── dvf/             archives trimestrielles (.csv.gz)
│   └── dpe/             archives trimestrielles (.csv.gz)
├── .github/workflows/   un workflow par projet
└── requirements.txt     dépendances partagées
```

Un dossier par projet, même squelette partout. Chaque projet a son README,
son schéma SQL et son workflow.

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg2://..."
```

Les scripts se lancent depuis la racine du dépôt :

```bash
python carburants/collect.py
python sncf/collect.py
python dvf/collect.py
python dpe/collect.py
```

---

## Conventions

Les mêmes règles s'appliquent à tous les projets. Elles viennent de pannes
réellement rencontrées, pas de principes théoriques.

| Règle | Pourquoi |
|---|---|
| Clé primaire naturelle et composite | Rend l'ingestion idempotente : relancer n'a aucun effet de bord. |
| Chargement vectorisé, jamais ligne à ligne | Le coût est dans le réseau, pas dans le calcul. |
| `sys.exit(1)` sur tout échec | Sans code de retour non nul, un run raté s'affiche en vert et passe inaperçu. |
| Identifiants stockés en `text` | `"01234"` n'est pas `1234`. Un code INSEE est un identifiant, pas un nombre. |
| Contrôles qualité bloquants | Mieux vaut un run rouge qu'une donnée fausse en base. |
| Archive froide committée chaque exécution | Protège l'historique, **et** maintient le dépôt actif — GitHub désactive les workflows planifiés après 60 jours d'inactivité. |
| `git pull --rebase` avant chaque commit automatique | Plusieurs workflows poussent sur ce dépôt ; sans ça, deux exécutions simultanées se rejettent. |
| Noms de champs vérifiés sur la source | Le nom d'un champ n'est pas sa documentation. |
| On archive ce qui est cher à refabriquer | Pas ce qui est gratuit à retélécharger. |
| Un dédoublonnage qui supprime = clé incomplète | Une clé bien choisie est déjà unique. |
| Pagination à curseur, jamais par offset | L'offset plafonne et tronque en silence. |
| Un croisement se publie avec son taux d'appariement | Sans lui, ce n'est pas un résultat mais une opinion. |
| Un résultat sans variable de contrôle est suspect | Il mesure surtout ce qu'on a oublié de mesurer. |

---

## Licence

Code sous licence MIT.
Données sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) —
Ministère de l'Économie (prix des carburants), SNCF (régularité TGV),
Etalab (DVF), ADEME (DPE).
