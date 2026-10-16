# Démarrage — ta part (≈ 20 min, tout dans le navigateur)

Tout le reste est prêt : code, tests dbt (8 modèles, 23 tests, vérifiés le 16/10/2026), workflow GitHub
`snowflake-dbt-daily` (tous les jours à 07:30 UTC). Tant que les étapes ci-dessous ne sont pas faites,
le workflow s'arrête proprement avec le message « Secrets Snowflake absents ».

L'authentification se fait **par clé** (pas de mot de passe de service) : Snowflake n'accepte plus la
connexion par simple mot de passe pour les nouveaux utilisateurs. La paire de clés a été générée sur ton PC :
`Desktop\Claude code V1\fuel-price-analytics\cle-snowflake\` (`rsa_key.p8` = clé **privée**, à ne jamais
envoyer à personne ni committer ; `rsa_key.pub` = clé publique, déjà intégrée à `snowflake/setup.sql`).

## 1. Créer le compte Snowflake (essai gratuit 30 jours) — 5 min
- https://signup.snowflake.com → édition **Standard**, cloud **AWS**, région **Europe (Frankfurt)** ou **Paris**.
- C'est toi qui crées le compte et ton mot de passe personnel (+ MFA si demandé).

## 2. Lancer le script de préparation — 5 min
- Dans Snowflake : **Projects → Workspaces** (ou Worksheets) → **+ SQL File**.
- Colle tout le contenu de `snowflake/setup.sql` (il est complet, rien à remplacer) → **Run All**.
- Résultat attendu : entrepôt `FUEL_WH`, base `FUEL_DB`, rôle `TRANSFORMER`, utilisateur de service
  `FUEL_SVC`, table `FUEL_DB.RAW.FUEL_PRICES_RAW`, moniteur de coût (10 crédits/mois max).

## 3. Récupérer l'identifiant du compte — 1 min
- En bas à gauche : ton nom → **Account** → **View account details** → copie l'**Account identifier**
  (format `ORGNAME-ACCOUNTNAME`). Ce n'est pas un secret : tu peux me le donner.

## 4. Ajouter 2 secrets dans GitHub — 5 min
- https://github.com/BoubacarDEMBELE/projet-carburants → **Settings** → **Secrets and variables** →
  **Actions** → **New repository secret** :
  - `SNOWFLAKE_ACCOUNT` = l'identifiant de l'étape 3
  - `SNOWFLAKE_PRIVATE_KEY` = **tout le contenu** du fichier `rsa_key.p8` (ouvre-le avec le Bloc-notes,
    Ctrl+A, Ctrl+C, colle ; les lignes `-----BEGIN PRIVATE KEY-----` et `-----END PRIVATE KEY-----` comprises).

## 5. Premier lancement — 1 min
- Onglet **Actions** → **snowflake-dbt-daily** → **Run workflow**.
- Ça dure environ 5 minutes. Dis-moi quand c'est lancé : je vérifie le résultat et je corrige si besoin.

## Coûts
Entrepôt XS (1 crédit/heure), arrêt automatique après 60 s, plafond de 10 crédits par mois. Un passage
quotidien consomme une fraction de crédit : l'essai (environ 400 $ de crédits) couvre largement le mois.
⚠️ À la fin des 30 jours d'essai, il faudra ajouter une carte ou arrêter le workflow (je te préviendrai).
