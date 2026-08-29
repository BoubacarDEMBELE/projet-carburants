-- Schéma — projet 5 : croisement DVF × DPE
-- À exécuter dans Supabase : SQL Editor -> New query -> Run
--
-- Cette table est une SOURCE NOUVELLE. Ni DVF ni l'ADEME ne la publient :
-- elle naît de l'appariement des deux, et n'existe nulle part ailleurs.

create table if not exists dvf_dpe (
    -- Clé héritée de dvf_vente : une ligne = une vente appariée à un DPE.
    id_mutation          text primary key references dvf_vente(id_mutation) on delete cascade,

    -- Côté vente (projet 4)
    date_mutation        date    not null,
    annee                integer not null,
    voie                 text,
    type_local           text,
    surface              numeric(10,2) not null,
    valeur_fonciere      numeric(14,2) not null,
    prix_m2              numeric(10,2) not null,

    -- Côté diagnostic (ADEME)
    etiquette_dpe        text not null,          -- A à G
    etiquette_ges        text,
    periode_construction text,                   -- le facteur de confusion, voir README
    identifiant_ban      text,
    conso_ep_m2          numeric(10,2),

    -- Traçabilité de l'appariement : on garde de quoi auditer la jointure.
    -- Sans ces deux colonnes, impossible de savoir a posteriori si un
    -- rapprochement était solide ou approximatif.
    surface_dpe          numeric(10,2),
    ecart_surface        numeric(6,4),           -- écart relatif retenu
    passoire             boolean not null,       -- étiquette F ou G

    collecte_le          timestamptz not null default now(),

    constraint etiquette_valide check (etiquette_dpe in ('A','B','C','D','E','F','G')),
    constraint ecart_tolere     check (ecart_surface <= 0.10)
);

create index if not exists idx_dvf_dpe_etiquette on dvf_dpe (etiquette_dpe);
create index if not exists idx_dvf_dpe_passoire  on dvf_dpe (passoire, annee);
create index if not exists idx_dvf_dpe_periode   on dvf_dpe (periode_construction);


-- ---------------------------------------------------------------------------
-- Vue : le résultat brut, celui qui trompe
-- ---------------------------------------------------------------------------
create or replace view v_prix_par_etiquette as
select
    etiquette_dpe,
    count(*)                                                    as nb_ventes,
    round(percentile_cont(0.5) within group (order by prix_m2)) as prix_m2_median,
    round(percentile_cont(0.5) within group (order by surface)) as surface_mediane
from dvf_dpe
group by etiquette_dpe
order by etiquette_dpe;


-- ---------------------------------------------------------------------------
-- Vue : le même écart, mais À PÉRIODE DE CONSTRUCTION COMPARABLE
--
-- C'est la vue qui compte. Le résultat brut suggère que les passoires se
-- vendent PLUS cher — ce qui est vrai, mais n'a rien à voir avec le DPE :
-- les passoires sont les logements anciens, et les logements anciens sont au
-- centre-ville. L'étiquette est un indicateur d'âge avant d'être un
-- indicateur de performance.
-- ---------------------------------------------------------------------------
create or replace view v_decote_controlee as
with base as (
    select periode_construction, passoire,
           count(*)                                                    as n,
           percentile_cont(0.5) within group (order by prix_m2)        as median
    from dvf_dpe
    where periode_construction is not null
    group by periode_construction, passoire
)
select
    p.periode_construction,
    p.n                                as n_passoires,
    a.n                                as n_autres,
    round(p.median)                    as median_passoires,
    round(a.median)                    as median_autres,
    round(100 * (p.median / a.median - 1), 1) as ecart_pct
from base p
join base a using (periode_construction)
where p.passoire and not a.passoire
  and p.n >= 15 and a.n >= 15
order by p.periode_construction;


-- ===========================================================================
-- REQUÊTES D'ANALYSE
-- ===========================================================================

-- Le résultat brut (trompeur) :
--   select * from v_prix_par_etiquette;

-- Le résultat contrôlé (le bon) :
--   select * from v_decote_controlee;

-- La preuve du facteur de confusion : les passoires sont les logements anciens
--   select periode_construction,
--          count(*) as n,
--          round(100.0 * count(*) filter (where passoire) / count(*), 0) as pct_passoires,
--          round(percentile_cont(0.5) within group (order by prix_m2)) as prix_median
--   from dvf_dpe
--   where periode_construction is not null
--   group by periode_construction
--   having count(*) >= 30
--   order by pct_passoires desc;

-- Double contrôle : même période ET même rue
--   select round(100 * (
--     percentile_cont(0.5) within group (order by prix_m2) filter (where passoire)
--     / nullif(percentile_cont(0.5) within group (order by prix_m2) filter (where not passoire), 0)
--     - 1), 1) as ecart_pct
--   from dvf_dpe;

-- Audit de la jointure : quelle était la qualité des rapprochements ?
--   select round(ecart_surface, 2) as ecart, count(*)
--   from dvf_dpe group by 1 order by 1;
