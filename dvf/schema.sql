-- Schéma — projet 4 : valeurs foncières (DVF), Saint-Germain-en-Laye
-- À exécuter dans Supabase : SQL Editor -> New query -> Run

-- ---------------------------------------------------------------------------
-- Une ligne = UNE MUTATION, jamais une ligne du fichier source.
--
-- C'est la décision de modélisation centrale du projet. Le fichier DVF
-- contient plusieurs lignes par vente (appartement + cave + parking), avec
-- le prix total répété à l'identique sur chacune. Modéliser « une ligne du
-- CSV = une ligne en base » reproduirait ce défaut et fausserait toute
-- statistique. On agrège donc AVANT d'insérer.
-- ---------------------------------------------------------------------------
create table if not exists dvf_vente (
    -- id_mutation vient de la source et identifie une vente. Il est donc une
    -- vraie clé primaire naturelle : pas besoin d'en fabriquer une.
    id_mutation      text primary key,

    date_mutation    date    not null,
    annee            integer not null,       -- dénormalisé : évite un extract() partout

    code_commune     text    not null,       -- TEXTE : "78551", pas un nombre
    nom_commune      text,
    code_postal      text,                   -- TEXTE : "01234" n'est pas 1234
    voie             text,

    type_local       text,                   -- Appartement / Maison
    nb_lots          integer,                -- lignes agrégées dans cette mutation
    nb_pieces        integer,
    surface          numeric(10,2) not null, -- somme des surfaces des lots
    valeur_fonciere  numeric(14,2) not null, -- prix total, pris une seule fois
    prix_m2          numeric(10,2) not null,

    collecte_le      timestamptz not null default now(),

    -- Garde-fous : la base refuse ce qui n'a pas de sens plutôt que de le stocker.
    constraint surface_positive check (surface > 0),
    constraint prix_plausible   check (prix_m2 between 500 and 30000)
);

-- ---------------------------------------------------------------------------
-- Index — les analyses filtrent par rue, par année ou par commune
-- ---------------------------------------------------------------------------
create index if not exists idx_dvf_voie    on dvf_vente (voie);
create index if not exists idx_dvf_annee   on dvf_vente (annee);
create index if not exists idx_dvf_commune on dvf_vente (code_commune, annee);

-- ---------------------------------------------------------------------------
-- Vue : évolution par rue, avec le contexte communal
--
-- Un prix isolé ne dit rien. C'est l'écart à la commune qui fait l'information.
-- Et `nb_ventes` est affiché systématiquement : une médiane sur 3 ventes
-- ne vaut rien, et le lecteur doit pouvoir le voir.
-- ---------------------------------------------------------------------------
create or replace view v_prix_par_rue as
with commune as (
    select annee,
           percentile_cont(0.5) within group (order by prix_m2) as median_commune
    from dvf_vente
    group by annee
)
select
    v.voie,
    v.annee,
    count(*)                                                      as nb_ventes,
    round(percentile_cont(0.5) within group (order by v.prix_m2)) as median_rue,
    round(c.median_commune)                                       as median_commune,
    round(100 * (percentile_cont(0.5) within group (order by v.prix_m2)
                 / c.median_commune - 1))                         as ecart_pct
from dvf_vente v
join commune c using (annee)
group by v.voie, v.annee, c.median_commune;


-- ===========================================================================
-- REQUÊTES D'ANALYSE
-- ===========================================================================

-- L'évolution d'une rue sur 5 ans :
--   select * from v_prix_par_rue
--   where voie = 'RUE DE TOURVILLE'
--   order by annee;

-- Les rues exploitables : au moins 5 ventes par an, sur les 5 années :
--   select voie, count(*) as nb_ventes, count(distinct annee) as annees,
--          round(percentile_cont(0.5) within group (order by prix_m2)) as median
--   from dvf_vente
--   group by voie
--   having count(distinct annee) = 5 and count(*) >= 25
--   order by nb_ventes desc;

-- Appartement contre maison :
--   select type_local, annee, count(*) as n,
--          round(percentile_cont(0.5) within group (order by prix_m2)) as median
--   from dvf_vente
--   group by type_local, annee
--   order by type_local, annee;

-- Le prix au m² décroît-il avec la surface ?
--   select width_bucket(surface, 0, 200, 8) * 25 as tranche_m2,
--          count(*) as n,
--          round(percentile_cont(0.5) within group (order by prix_m2)) as median
--   from dvf_vente
--   group by 1 order by 1;

-- Contrôle du quota Free Tier :
--   select pg_size_pretty(pg_total_relation_size('dvf_vente')) as taille,
--          count(*) as lignes from dvf_vente;
