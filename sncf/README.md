# Projet 3 — Régularité TGV : consommation d'API

![Collecte mensuelle](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/sncf_monthly.yml/badge.svg)

Collecte mensuelle de la régularité des liaisons TGV, avec archive brute et
table structurée. **8 ans d'historique, 12 544 observations.**

> **La question de départ** : quelles liaisons concentrent les retards,
> est-ce saisonnier, et quelle en est la cause principale ?

---

## Source

[Régularité mensuelle TGV par liaison](https://ressources.data.sncf.com/explore/dataset/regularite-mensuelle-tgv-aqst/),
publié par SNCF sous Licence Ouverte. API REST sans clé.

Période couverte : **2018-01 → 2026-06**, 12 544 enregistrements.

---

## Le piège de l'extraction

L'endpoint `/records` plafonne à `offset + limit <= 10000`. Au-delà il renvoie
un `400`. Sur ce jeu de 12 544 lignes, une pagination classique en récupère
**10 000 et s'arrête** — soit 20 % de données manquantes, **sans erreur
explicite**. Le seul signal est le chiffre rond.

```
Fin d'extraction (Status 400) à l'offset 10000.
Extraction terminée : 10000 enregistrements récupérés.
```

La solution : `/exports/json`, qui n'a pas de plafond et renvoie tout en un
appel. C'est ce que fait `collect.py`.

> **Règle générale** : un chiffre rond est presque toujours un chiffre faux.
> Exactement 10 000 lignes, ce n'est pas la réalité, c'est une limite.

---

## Architecture

```
API ressources.data.sncf.com
        │  extraction — /exports/json, un seul appel
        ▼
GitHub Actions (le 5 de chaque mois, 8h UTC)
        │  transformation — Pandas, dérivations, contrôle qualité
        ├──────────────► data/sncf/AAAA-MM-JJ.json.gz   (archive brute, Git)
        │  chargement — upsert sur clé naturelle
        ▼
Supabase PostgreSQL — table sncf_regularite
```

**Cadence mensuelle et non quotidienne** : la source est mensuelle. Collecter
tous les jours retéléchargerait des données identiques, pour 449 Mo d'archive
par an au lieu de 15 Mo.

**Archive brute dans Git, pas en base.** Une première version insérait une
ligne JSONB par enregistrement, soit 12 544 lignes par exécution sans clé
d'unicité : chaque relance empilait un jeu complet. Sur un Free Tier de
500 Mo, c'est intenable. Même architecture chaud/froid que le projet 2.

---

## Le contrôle qualité

Les six causes de retard totalisent 100 %. Le script vérifie cette somme et
**échoue** si plus de 5 % des lignes dévient — c'est le signal qu'un champ a
changé de nom côté source.

Ce contrôle existe parce qu'une première version n'en mappait que cinq :
la somme tombait à 95 %, sans aucune erreur, et la répartition des causes
était fausse de 5 points.

| Cause | Champ source |
|---|---|
| Externe | `prct_cause_externe` |
| Infrastructure | `prct_cause_infra` |
| Matériel roulant | `prct_cause_materiel_roulant` |
| Gestion du trafic | `prct_cause_gestion_trafic` |
| Gestion en gare | `prct_cause_gestion_gare` |
| Prise en charge voyageurs | `prct_cause_prise_en_charge_voyageurs` |

---

## Correspondance des champs

Les noms devinés ne fonctionnent pas. Ceux-ci ont été relevés sur l'API.

| Attendu intuitivement | Champ réel |
|---|---|
| `depart_station` | `gare_depart` |
| `arrival_station` | `gare_arrivee` |
| `nombre_pressentis_pour_circuler` | `nb_train_prevu` |
| `nombre_annules` | `nb_annulation` |
| `nombre_de_trains_en_retard_a_l_arrivee` | `nb_train_retard_arrivee` |
| `retard_moyen_de_tous_les_trains_a_l_arrivee` | `retard_moyen_tous_trains_arrivee` |
| `retard_moyen_des_trains_en_retard_a_l_arrivee` | `retard_moyen_arrivee` |
| `axe` | n'existe pas → `service` |
| `nombre_en_service` | n'existe pas → dérivé de `nb_train_prevu - nb_annulation` |

---

## Structure

```
sncf/
├── collect.py                        extraction, transformation, chargement
├── schema.sql                        table, index, vue, requêtes d'analyse
└── README.md                         ce fichier

à la racine du dépôt :
├── .github/workflows/sncf_monthly.yml   cron mensuel + commit de l'archive
├── data/sncf/                            archive brute (générée)
└── requirements.txt                      dépendances partagées
```

## Utilisation

```bash
python sncf/collect.py
```

Créer la table : exécuter `sncf/schema.sql` dans le SQL Editor de Supabase.

---

## Limites connues

- La source est publiée avec plusieurs mois de décalage : le dernier mois disponible n'est jamais le mois courant.
- Les liaisons apparaissent et disparaissent au fil des années ; une comparaison sur 8 ans doit en tenir compte.
- `nombre_circules` est dérivé, pas fourni par la source.
- Les colonnes de commentaires (`commentaire_annulation`, `commentaires_retard_arrivee`) sont ignorées : très majoritairement vides.

---

*Projet 3 du parcours. Voir le [README du dépôt](../README.md) pour l'ensemble des projets.*
