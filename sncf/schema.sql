-- Schéma — projet 3 : régularité mensuelle TGV (SNCF)
-- À exécuter dans Supabase : SQL Editor -> New query -> Run
--
-- ⚠️ RECONSTRUIT À PARTIR DU CODE, PAS EXPORTÉ DE LA BASE.
-- Déduit des requêtes INSERT de sncf/collect.py. Vérifie-le une fois avec
-- la requête de contrôle en bas, puis supprime cet avertissement.

-- ---------------------------------------------------------------------------
-- Une ligne par liaison et par mois.
-- ---------------------------------------------------------------------------
create table if not exists sncf_regularite (
    -- Clé naturelle : "AAAA-MM_GARE_DEPART_GARE_ARRIVEE".
    -- Composée à partir de la source, elle rend l'ingestion idempotente
    -- sans dépendre d'un identifiant que l'API ne fournit pas.
    id_liaison_mois               text primary key,

    annee_mois                    text not null,      -- format "2018-01"
    axe                           text,               -- National / International
    depart                        text not null,
    arrivee                       text not null,

    nombre_programmes             integer,
    nombre_circules               integer,            -- dérivé : programmés - annulés
    nombre_annules                integer,
    nombre_retard_arrivee         integer,

    retard_moyen_tous_trains      numeric,            -- minutes, tous trains
    retard_moyen_trains_en_retard numeric,            -- minutes, trains en retard seulement

    -- Les 6 causes totalisent 100 %. En omettre une fausse silencieusement
    -- toute répartition : avec 5 sur 6, la somme tombe à ~95 %.
    cause_externe_pct             numeric,
    cause_infrastructure_pct      numeric,
    cause_materiel_pct            numeric,
    cause_exploitation_pct        numeric,
    cause_gestion_gare_pct        numeric,
    cause_voyageurs_pct           numeric,

    collecte_le                   timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Index — les analyses filtrent par période, par liaison ou par axe
-- ---------------------------------------------------------------------------
create index if not exists idx_sncf_mois    on sncf_regularite (annee_mois);
create index if not exists idx_sncf_liaison on sncf_regularite (depart, arrivee);
create index if not exists idx_sncf_axe     on sncf_regularite (axe);

-- ---------------------------------------------------------------------------
-- Vue : la dernière période disponible, classée par retard moyen
-- ---------------------------------------------------------------------------
create or replace view v_sncf_dernier_mois as
select
    annee_mois,
    depart,
    arrivee,
    nombre_programmes,
    nombre_retard_arrivee,
    retard_moyen_tous_trains,
    round(100.0 * nombre_retard_arrivee / nullif(nombre_programmes, 0), 1) as pct_trains_en_retard
from sncf_regularite
where annee_mois = (select max(annee_mois) from sncf_regularite)
order by retard_moyen_tous_trains desc nulls last;


-- ===========================================================================
-- CONTRÔLE — compare ce fichier à la vraie base
-- ===========================================================================
-- select column_name, data_type, is_nullable
-- from information_schema.columns
-- where table_schema = 'public' and table_name = 'sncf_regularite'
-- order by ordinal_position;


-- ===========================================================================
-- CONTRÔLE QUALITÉ — la somme des causes doit valoir ~100 %
-- ===========================================================================
-- select count(*) as lignes_hors_norme
-- from sncf_regularite
-- where coalesce(cause_externe_pct,0) + coalesce(cause_infrastructure_pct,0)
--     + coalesce(cause_materiel_pct,0) + coalesce(cause_exploitation_pct,0)
--     + coalesce(cause_gestion_gare_pct,0) + coalesce(cause_voyageurs_pct,0)
--       not between 99 and 101
--   and cause_externe_pct is not null;


-- ===========================================================================
-- REQUÊTES D'ANALYSE — la matière des posts
-- ===========================================================================

-- La cause n°1 de retard, toutes liaisons confondues, par année :
--   select left(annee_mois, 4) as annee,
--          round(avg(cause_externe_pct), 1)        as externe,
--          round(avg(cause_infrastructure_pct), 1) as infrastructure,
--          round(avg(cause_materiel_pct), 1)       as materiel,
--          round(avg(cause_exploitation_pct), 1)   as exploitation,
--          round(avg(cause_gestion_gare_pct), 1)   as gestion_gare,
--          round(avg(cause_voyageurs_pct), 1)      as voyageurs
--   from sncf_regularite
--   group by 1 order by 1;

-- Top 10 des liaisons les plus en retard (minimum 500 trains programmés) :
--   select depart, arrivee,
--          sum(nombre_programmes) as trains,
--          round(avg(retard_moyen_tous_trains), 2) as retard_moyen
--   from sncf_regularite
--   group by depart, arrivee
--   having sum(nombre_programmes) >= 500
--   order by retard_moyen desc
--   limit 10;

-- Saisonnalité : le retard moyen mois par mois sur 8 ans :
--   select right(annee_mois, 2) as mois,
--          round(avg(retard_moyen_tous_trains), 2) as retard_moyen
--   from sncf_regularite
--   group by 1 order by 1;

-- Évolution du taux d'annulation par année :
--   select left(annee_mois, 4) as annee,
--          round(100.0 * sum(nombre_annules) / nullif(sum(nombre_programmes), 0), 2) as pct_annulation
--   from sncf_regularite
--   group by 1 order by 1;
