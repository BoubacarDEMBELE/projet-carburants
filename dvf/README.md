# Projet 4 — Valeurs foncières : le nettoyage de données réelles

![Collecte trimestrielle](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/dvf_quarterly.yml/badge.svg)

Prix au m² à Saint-Germain-en-Laye, rue par rue, sur 5 ans.
**2 927 ventes exploitables extraites de 10 119 lignes brutes.**

> **La question de départ** : combien vaut le m² dans une rue donnée, et
> comment a-t-il bougé par rapport au reste de la ville ?

---

## Le résultat

**Rue de Tourville**, Saint-Germain-en-Laye — 128 ventes sur 5 ans.

| Année | Ventes | Médiane €/m² | Commune | Écart |
|---|---|---|---|---|
| 2021 | 26 | 6 503 | 6 467 | +1 % |
| 2022 | 26 | 7 182 | 6 782 | +6 % |
| 2023 | 24 | 6 297 | 6 557 | −4 % |
| 2024 | 28 | 6 906 | 6 471 | +7 % |
| 2025 | 24 | 6 897 | 6 406 | +8 % |

**La rue : +6,0 % sur 5 ans. La commune entière : −0,9 %.**

Un prix isolé ne dit rien. C'est la comparaison au contexte qui fait
l'information — et l'écart se creuse régulièrement, de +1 % à +8 %.

---

## Source

[Demandes de valeurs foncières géolocalisées](https://files.data.gouv.fr/geo-dvf/latest/csv/),
publiées par Etalab sous Licence Ouverte. Toutes les ventes immobilières
déclarées en France.

Périmètre : département 78, commune 78551, années 2021 à 2025.
Le dossier `latest` couvre 5 années glissantes.

---

## L'entonnoir de nettoyage

C'est le cœur du projet. Chaque règle est mesurée et journalisée à chaque
exécution — une règle qui se met à retirer 90 % des lignes est un signal
que la source a changé.

```
10 119   lignes brutes
 9 056   nature_mutation = Vente              −1 063
 3 459   type_local = Appartement/Maison      −5 597
 3 454   prix et surface renseignés               −5
 2 987   1 ligne = 1 mutation                   −467
 2 927   écrêtage 1 %–99 %                       −60
         conservé : 29 %
```

### 1. Ne garder que les ventes
Échanges, expropriations et adjudications ont des prix qui ne reflètent pas
le marché.

### 2. Ne garder que les logements
La règle la plus coûteuse — 5 597 lignes. Ce n'est **pas une perte** : caves,
parkings, terrains et dépendances n'ont pas de prix au m² habitable. C'est la
définition du périmètre.

### 3. Le piège des ventes multi-lots
Une même vente couvre souvent plusieurs lignes : appartement + cave + parking.
Sur **chacune**, `valeur_fonciere` porte le prix **total**, répété à
l'identique. Vérifié sur ce jeu :

```
mutations multi-lignes où le prix est identique partout : 187/187
```

Sans agrégation, une vente à 500 000 € étalée sur 3 lignes compte trois fois.
Sommer les prix serait pire encore : on obtiendrait 1 500 000 €.

L'opération correcte : **une ligne par mutation, surfaces sommées, prix pris
une seule fois.**

```python
.agg(
    valeur_fonciere=("valeur_fonciere", "first"),   # first, jamais sum
    surface=("surface_reelle_bati", "sum"),         # sum, jamais first
)
```

### 4. Les valeurs aberrantes
Le brut va de **0 à 103 472 €/m²**. Sans écrêtage, aucune moyenne n'a de sens.

L'écrêtage se fait aux percentiles 1 % et 99 %, pas à des seuils en dur : la
règle reste valable si on change de commune.

---

## Les pièges de typage

| Piège | Conséquence | Correctif |
|---|---|---|
| `code_commune` lu comme un entier | `"01234"` devient `1234`, la jointure échoue | `dtype={"code_commune": str}` |
| `code_postal` idem | Même problème | `dtype={"code_postal": str}` |
| Moyenne au lieu de médiane | Une vente atypique décale tout sur de petits volumes | `percentile_cont(0.5)` |
| Médiane sans effectif affiché | Une médiane sur 3 ventes ne vaut rien | `nb_ventes` systématiquement affiché |

---

## Décisions techniques

| Décision | Pourquoi |
|---|---|
| Filtrage commune **avant** le reste | On porte 10 000 lignes en mémoire au lieu de 294 000. |
| `usecols` : 11 colonnes sur 40 | Divise par ~4 la mémoire utilisée. |
| Décompression en mémoire | Inutile d'écrire 2 Mo sur le disque à chaque année. |
| Une ligne en base = une mutation | Modéliser « une ligne du CSV = une ligne en base » reproduirait le défaut de la source. |
| `id_mutation` en clé primaire | Vraie clé naturelle fournie par la source : rien à fabriquer. |
| Archive du jeu **nettoyé**, pas du brut | Le brut est retéléchargeable et pèse 9 Mo ; le nettoyé pèse 67 Ko et incorpore toutes les règles. **On archive ce qui est cher à refabriquer.** |
| Contraintes `check` en base | La base refuse une valeur aberrante plutôt que de la stocker. |
| Cadence trimestrielle | DVF n'est republié que deux fois par an. |

---

## Structure

```
dvf/
├── collect.py                        extract / transform / load
├── schema.sql                        table, index, vue, requêtes d'analyse
└── README.md                         ce fichier

à la racine du dépôt :
├── .github/workflows/dvf_quarterly.yml
├── data/dvf/                          archive du jeu nettoyé (générée)
└── requirements.txt
```

## Utilisation

```bash
python dvf/collect.py --dry-run
python dvf/collect.py
```

Créer la table : exécuter `dvf/schema.sql` dans le SQL Editor de Supabase.

---

## Limites connues

- **Rue de Tourville a été choisie pour son volume** (128 ventes, la plus fournie de la commune), pas pour un lien avec l'auteur.
- DVF ne couvre pas l'Alsace-Moselle ni Mayotte, qui relèvent d'un autre régime.
- Le prix déclaré peut inclure du mobilier ou des frais, ce qui le gonfle légèrement.
- Une médiane annuelle sur moins de 5 ventes n'est pas interprétable — d'où l'affichage systématique de l'effectif.
- Le périmètre est volontairement limité à une commune, pour tenir dans le Free Tier Supabase.

---

*Projet 4 du parcours. Voir le [README du dépôt](../README.md) pour l'ensemble des projets.*
