# Projet 5 — DVF × DPE : croiser deux sources sans clé commune

![Croisement](https://github.com/BoubacarDEMBELE/projet-carburants/actions/workflows/dpe_quarterly.yml/badge.svg)

Une passoire thermique se vend-elle moins cher ?
**2 562 ventes appariées à leur diagnostic énergétique, taux d'appariement 87,5 %.**

> Ce projet crée une **source qui n'existe nulle part** : ni DVF ni l'ADEME ne
> publient ce rapprochement.

---

## La réponse courte

**Non — et l'inverse apparent est un piège.**

| Contrôle appliqué | Écart de prix des passoires |
|---|---|
| Aucun (brut) | **+8,5 %** |
| À surface et type comparables | +10,1 % |
| À période de construction comparable | +7,0 % |
| À période **et** rue comparables | **+3,2 %** |
| Parmi les logements d'avant 1948 | **+0,9 %** |

L'écart fond à mesure qu'on contrôle. **Il ne reste presque rien.**

---

## Pourquoi les passoires semblaient se vendre plus cher

Le facteur de confusion est l'**âge du bâti**.

| Période de construction | Part de passoires | Prix médian |
|---|---|---|
| avant 1948 | **24 %** | **7 500 €/m²** |
| 1948-1974 | 18 % | 6 000 €/m² |
| 1975-1977 | 8 % | 4 229 €/m² |
| 1989-2000 | 1 % | 5 408 €/m² |
| après 2001 | **0 %** | 4 867–6 194 €/m² |

Les logements anciens sont mal isolés **et** situés au centre historique.
L'étiquette DPE est d'abord un indicateur d'âge, et l'âge est un indicateur
d'emplacement.

Confirmation par les rues : la corrélation entre le prix médian d'une rue et
sa part de passoires est de **+0,39**. Les rues les plus chères (Thiers,
Alsace, Noailles) comptent 10 à 21 % de passoires ; les moins chères
(Franz Schubert, César Franck, Baron) en comptent **0 %** — ce sont des
immeubles récents.

<br>

> **La leçon** : croiser deux sources donne une réponse. Ajouter les contrôles
> montre que la réponse était fausse. Un croisement sans variable de contrôle
> mesure surtout ce qu'on a oublié de mesurer.

---

## Sources

| Source | Volume | Accès |
|---|---|---|
| Ventes (projet 4) | 2 927 sur la commune | table `dvf_vente` |
| [DPE logements existants](https://data.ademe.fr/datasets/meg-83tjwtg8dyz4vv7h1dqe) | 15,4 M en France, **14 081 sur la commune** | API Data Fair, sans clé |

Le projet 5 **relit la sortie du projet 4** plutôt que de refaire le nettoyage.
Une pipeline consomme la sortie d'une autre : c'est ce qui évite deux
définitions divergentes de « une vente propre ».

---

## Le problème : aucune clé commune

DVF et DPE n'ont **aucun identifiant partagé**. La jointure doit être
construite.

### La normalisation des noms de voie

DVF écrit `AV MAL FOCH`. L'ADEME écrit `Avenue du Maréchal Foch`.
Sans traitement, ces deux chaînes ne se rencontrent jamais.

| Étape | Couverture des ventes |
|---|---|
| Majuscules, accents, ponctuation | 86,8 % |
| **+ abréviations et articles** | **97,0 %** |

Dix points gagnés avec deux règles : développer les abréviations
(`AV` → `AVENUE`, `MAL` → `MARECHAL`, `PDT` → `PRESIDENT`) et retirer les
articles en tête (`DU`, `DE LA`, `DES`).

### L'appariement

Rue normalisée + surface à **±10 %**, puis le DPE le plus proche en surface.

| Tolérance | Ventes appariées | Taux |
|---|---|---|
| ±3 % | 2 210 | 75,5 % |
| ±5 % | 2 433 | 83,1 % |
| **±10 %** | **2 562** | **87,5 %** |
| ±20 % | 2 686 | 91,8 % |

±10 % est un compromis assumé : les deux sources ne mesurent pas la même
chose (surface bâtie contre surface habitable). Élargir monterait le taux mais
dégraderait la qualité des rapprochements.

`ecart_surface` est **conservé en base** : sans lui, impossible d'auditer
a posteriori si un rapprochement était solide ou approximatif.

---

## Le piège de pagination, troisième rencontre

L'API ADEME plafonne une page à 10 000 lignes. Avec 14 081 DPE sur la commune,
une pagination par `offset` en perdrait **4 081** — silencieusement, avec pour
seul signal un chiffre rond.

La réponse porte un champ `next` : une URL complète à suivre jusqu'à
disparition. **Un curseur n'a pas de plafond, contrairement à un offset.**

Détail qui coûte une exception : `total` n'est présent que sur la **première**
page.

---

## Décisions techniques

| Décision | Pourquoi |
|---|---|
| Pagination à curseur, pas par offset | Seule façon de dépasser 10 000 lignes. |
| Relire `dvf_vente` plutôt que refaire le nettoyage | Une seule définition de « vente propre ». |
| Tolérance de surface conservée en base | Permet d'auditer la qualité de chaque rapprochement. |
| Échec si le taux d'appariement passe sous 50 % | Mieux vaut un run rouge qu'une analyse publiée sur un échantillon biaisé. |
| Vue `v_decote_controlee` à côté de `v_prix_par_etiquette` | La vue brute est trompeuse ; les deux sont exposées pour montrer l'écart. |
| Taux d'appariement journalisé et publié | Un croisement dont on tait le taux n'est pas un résultat, c'est une opinion. |

---

## Limites connues

- **Le résultat n'est pas causal.** Les contrôles réduisent le biais, ils ne l'éliminent pas.
- Il manque une variable d'emplacement fine (IRIS, distance au centre) pour conclure proprement. **Répondre à la question demanderait une troisième source.**
- Un DPE apparié n'est pas forcément *celui du logement vendu* : même rue, surface proche, mais rien ne le prouve. C'est la limite intrinsèque d'une jointure sans clé.
- Les DPE datent de juillet 2021 au plus tôt ; les ventes de 2021 sont donc moins bien couvertes.
- Périmètre d'une seule commune : le résultat ne se généralise pas.

---

## Structure

```
dpe/
├── collect.py                        extraction, normalisation, jointure, chargement
├── schema.sql                        table, vues brute et contrôlée, requêtes
└── README.md                         ce fichier

à la racine du dépôt :
├── .github/workflows/dpe_quarterly.yml
├── data/dpe/                          archive du jeu croisé (générée)
└── requirements.txt
```

## Utilisation

```bash
python dpe/collect.py --dry-run
python dpe/collect.py
```

Prérequis : `dvf_vente` doit être remplie (projet 4).
Créer la table : exécuter `dpe/schema.sql` dans le SQL Editor de Supabase.

---

*Projet 5 du parcours. Voir le [README du dépôt](../README.md) pour l'ensemble des projets.*
