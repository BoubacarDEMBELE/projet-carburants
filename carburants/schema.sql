-- Schéma de la base — projet prix des carburants
-- À exécuter dans Supabase : SQL Editor -> New query -> Run
--
-- ⚠️ RECONSTRUIT À PARTIR DU CODE, PAS EXPORTÉ DE LA BASE.
-- Ce fichier a été déduit des requêtes INSERT / ON CONFLICT de
-- collect_carburants.py. Il doit être conforme, mais vérifie-le une fois
-- avec la requête de contrôle en bas de ce fichier, puis supprime cet
-- avertissement.

-- ---------------------------------------------------------------------------
-- Dimension : les stations. Change rarement.
-- ---------------------------------------------------------------------------
create table if not exists station (
    id_station   bigint primary key,          -- identifiant fourni par le flux
    adresse      text,
    ville        text,
    cp           text,                        -- TEXTE : "01234" n'est pas 1234
    latitude     double precision,
    longitude    double precision,
    distance_km  numeric(6,2)                 -- NULL aujourd'hui, voir README
);

-- ---------------------------------------------------------------------------
-- Fait : une ligne par station x carburant x jour.
-- ---------------------------------------------------------------------------
create table if not exists prix_carburant (
    id_station   bigint       not null references station(id_station) on delete cascade,
    carburant    text         not null,       -- Gazole, SP95, SP98, E10, E85, GPLc
    prix         numeric(6,3) not null,
    date_releve  date         not null,       -- le jour de la collecte
    collecte_le  timestamptz  not null default now(),

    -- Clé primaire composite = idempotence.
    -- C'est elle qui rend le ON CONFLICT DO UPDATE possible, donc qui permet
    -- de relancer le script plusieurs fois par jour sans créer de doublon.
    primary key (id_station, carburant, date_releve)
);

-- ---------------------------------------------------------------------------
-- Index — la purge et les analyses filtrent toutes sur la date
-- ---------------------------------------------------------------------------
create index if not exists idx_prix_date      on prix_carburant (date_releve);
create index if not exists idx_prix_carb_date on prix_carburant (carburant, date_releve);

-- ---------------------------------------------------------------------------
-- Vue : les moins chères du dernier relevé
-- ---------------------------------------------------------------------------
create or replace view v_moins_cheres_du_jour as
select
    p.carburant,
    p.prix,
    s.ville,
    s.adresse,
    s.cp,
    p.date_releve,
    rank() over (partition by p.carburant order by p.prix) as rang
from prix_carburant p
join station s using (id_station)
where p.date_releve = (select max(date_releve) from prix_carburant);


-- ===========================================================================
-- REQUÊTE DE CONTRÔLE — compare ce fichier à la vraie base
-- ===========================================================================
-- select table_name, column_name, data_type, is_nullable
-- from information_schema.columns
-- where table_schema = 'public' and table_name in ('station','prix_carburant')
-- order by table_name, ordinal_position;


-- ===========================================================================
-- SURVEILLANCE DU QUOTA (Free Tier : 500 Mo)
-- ===========================================================================
-- select pg_size_pretty(pg_total_relation_size('prix_carburant')) as taille_prix,
--        pg_size_pretty(pg_total_relation_size('station'))        as taille_station,
--        (select count(*) from prix_carburant)                    as lignes,
--        (select count(distinct date_releve) from prix_carburant)  as jours_conserves;


-- ===========================================================================
-- REQUÊTES D'ANALYSE
-- ===========================================================================
-- Les 5 stations les moins chères en gazole aujourd'hui :
--   select * from v_moins_cheres_du_jour where carburant = 'Gazole' and rang <= 5;
--
-- L'écart min/max jour par jour — le chiffre du post LinkedIn :
--   select date_releve, min(prix) as mini, max(prix) as maxi,
--          round(max(prix) - min(prix), 3) as ecart
--   from prix_carburant where carburant = 'Gazole'
--   group by date_releve order by date_releve;
--
-- Variation quotidienne par station (fonction fenêtre) :
--   select id_station, date_releve, prix,
--          prix - lag(prix) over (partition by id_station order by date_releve) as variation
--   from prix_carburant where carburant = 'Gazole';
