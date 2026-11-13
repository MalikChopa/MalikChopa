# Exploitation de Sol-0 / Operating Sol-0

*English summary at the end of each section.*

## Le workflow `sol`
- Fichier : `.github/workflows/sol.yml`. Déclencheur : `workflow_dispatch` seulement (plus de `schedule` : c'est le serveur qui fait vivre le rover ; Actions ne sert qu'à `check`, `restore`, `refs`). Ne pas lancer le mode `sol` tant que le serveur vit le rover.
- Modes manuels (`gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=<mode>`) :
  - `sol` : un sol (par défaut pour le planning) ;
  - `check` : valide l'état publié, n'écrit rien ;
  - `refs` : calcule les empreintes de référence (imprimées dans le journal du job, entre `REFS-BEGIN` et `REFS-END`, et dans le résumé) ;
  - `restore` avec `-f checkpoint=sol-NNNNNN` (ou `-f checkpoint=schema-N`, voir « Retour au code v1 ») : republie un checkpoint nommé après validation, `epoch + 1` ; ne supprime jamais la branche `state`.
- Ordre de publication : branche `state` (source de vérité), tags, puis `journal/ atlas/ firsts/` sur `main`.
- Codes de `publish.sh` : 0 succès ; 1 rouge après publication (3 sols passifs de suite, ou `main` refusé avec `main_lag` ≥ 2) ; 4 push de `state` impossible après 4 essais ; 5 `state` modifié par un autre écrivain (bail refusé), rien d'autre n'est poussé.
- *EN: manual dispatch only (no schedule: the server lives the rover); modes sol, check, refs, restore; state first, then tags, then main.*

## Réactivation (règle des 60 jours de GitHub)
GitHub désactive les workflows planifiés d'un dépôt public sans activité pendant 60 jours. Décision F1 : **aucun commit vide, aucune réactivation par l'API** ; la seule activité est le vrai produit (commit d'état, commit du journal). Si le workflow est désactivé :
- interface : Actions, `sol`, « Enable workflow » ;
- ligne de commande : `gh workflow enable sol.yml -R <propriétaire>/<dépôt>`, puis `gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=sol`.
Condition : aucune protection de `main` qui exige une PR (ou une exception pour `github-actions[bot]`). Sinon le push du journal est refusé : l'entrée reste dans `journal_tail` et le run devient rouge au 3e échec de suite.
La date du dernier contact figure dans `console.gif` et `status.svg`.
*EN: re-enable with `gh workflow enable`; no empty commits, ever (decision F1, to be re-validated by the owner).*

## Restauration
1. Lister les checkpoints : branche `state`, dossier `state/checkpoints/` (5 `sol-*` gardés ; `schema-N` hors rotation, voir plus bas).
2. `gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=restore -f checkpoint=sol-000123`.
3. Vérifier le run, puis `status.json` (`det.restored_from`) sur la branche `state`.
Un état corrompu est restauré automatiquement par `rover sol` (checkpoint sain le plus récent, `epoch + 1`). Un état plus récent que le code (schéma, stade) est refusé (code 3) : sortie par `mode=restore` ou par un nouveau code.
*EN: restore with mode=restore and the checkpoint name.*

## Retour au code v1 (schéma 2 vers schéma 1, SPEC 6.14.7, cas 20)
Le premier sol joué par le code v2 sur un état v1 le migre (schéma 1 vers 2) et écrit `state/checkpoints/schema-1.json.gz` (+ `.sha256`) : le core v1, octet pour octet, **hors rotation** (recopié à chaque sol, jamais supprimé par la rotation des 5 `sol-*`). Les blocs de la mémoire d'échantillons (`state/memory/b_<i>.bin.gz`, 256 lignes par bloc, au plus 4 096 lignes) n'existent qu'en schéma 2.
Procédure (l'utilisateur la lance, jamais un agent) :
1. Avec le code **v2** encore sur `main` : `gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=restore -f checkpoint=schema-1`. Le run republie le core v1 tel quel (`schema_version` 1, `epoch + 1`, cause `manual`, ligne de journal de restauration), avec les régions explorées, **sans** blocs de mémoire ni checkpoints `sol-*` (ils sont de schéma 2 : un code v1 les refuserait, code 3). Un checkpoint `sol-N` de schéma 1 est écrit par la restauration elle-même.
2. Remettre le code v1 (tag `p1`) sur `main`. Le code v1 charge cet état normalement ; un état v2 donné au code v1 est refusé (code 3, rien d'écrit, jamais de restauration).
3. Vérifier `status.json` (`det.schema_version` = 1, `det.restored_from` = `schema-1`) sur la branche `state`.
Limites : si plus de 5 sols v2 ont tourné, plus aucun checkpoint `sol-*` de schéma 1 n'existe (sortis de la rotation) : le premier sol joué par le code v1 part donc sans checkpoint `sol-*` de schéma 1 (une corruption à ce sol ne serait pas réparable par le code v1). Si l'étape 2 n'a pas lieu, le run v2 suivant re-migre l'état (sans perte, réversible), et réécrit `schema-1.json.gz` à partir du core v1 publié. Les noms acceptés par `rover restore` et par `tools/ci/validate_inputs.py` sont `^(sol-[0-9]{6}|schema-[1-9][0-9]?)$`.
Les échantillons pris par le rover entre la migration et le retour sont perdus pour le code v1 (il ne les connaît pas) ; ils restent dans l'historique de la branche `state`.
*EN: to go back to v1, run mode=restore with checkpoint=schema-1 while the v2 code is on main, then put the v1 code (tag p1) back. schema-1 is kept out of the 5-checkpoint rotation; samples taken after the migration are not carried back.*

## Mémoire d'échantillons (schéma 2)
`state/memory/b_<i>.bin.gz` : bloc i = lignes d'identifiant 256·i à 256·i + 255 ; un sol ne réécrit que le dernier bloc. Au-delà de 4 096 lignes, le bloc le plus ancien est retiré en entier. `state/checkpoints/memory/` garde la version précédente des blocs modifiés ou retirés au dernier sol. Un bloc illisible à la restauration est remplacé par sa copie de garde ; s'il n'y en a pas, il est déclaré perdu dans le journal du chargement (`memory block b_<i> lost`) et jamais reconstitué.
*EN: sample memory blocks, 256 rows each, oldest block evicted above 4096 rows, guard copies in checkpoints/memory.*

## Écrivain extérieur sur `state`
Un commit manuel sur `state` pendant un run fait refuser le bail (code 5, run rouge, rien d'autre poussé). Le run suivant lit l'état modifié et le réécrit : tout fichier ajouté à la main sur `state` disparaît. Ne pas écrire sur `state` à la main.

## Taille du dépôt
`publish.sh` relève `gh api repos/<dépôt> --jq .size` (Ko) : `::notice::` sinon `::warning::` au-delà de `repo_size_alert_kb` (1 048 576 Ko = 1 Go, `config/run.toml`). La valeur renvoyée par GitHub est différée. Parades au-delà de 1 Go : demander un nettoyage au support GitHub, ou espacer les checkpoints. La purge des anciens commits orphelins de `state` prend des semaines (non documentée, non mesurée).

## Mise en ligne sur le profil (jamais lancée par un agent ; seulement avec l'accord de l'utilisateur)
1. Copie datée du README de profil ; relecture des protections (`gh api repos/<compte>/<compte>/rulesets`, protection de `main`).
2. `.venv/bin/python tools/export_public.py --out out/prod` ; l'utilisateur relit la liste (`--list`).
3. PR 1, branche `sol-0-setup` issue du `main` du profil : code et workflow, **sans** la section README (le commit sans historique de l'export ne sert pas de base : GitHub refuse une PR sans ancêtre commun). Après fusion par l'utilisateur : `gh workflow run sol.yml -R <compte>/<compte> -f mode=sol`, vérifier `state` et les URL brutes.
4. PR 2 : `tools/set_repo.py --prod --repo <compte>/<compte> --readme README.md --out README.md` sur une copie, section entre `<!-- sol-0:start -->` et `<!-- sol-0:end -->` (les marqueurs du code et de `pages/readme-section.md`, voir `docs/GOLIVE.md` ; ne pas les confondre avec `<!-- PROJETS:DEBUT -->` / `<!-- PROJETS:FIN -->` du bot du profil, qui restent intacts). `pages/` doit être à la racine de `main` (liens relatifs de la section).
5. 14 jours de suivi ; noter ici la date de mise en ligne et celle du dernier contact.
*EN: go-live is two PRs, after the owner's approval; never run by an agent.*

Note : `tools/compare_refs.py --run` appelle `gh` ; le lancer avec le `HOME` normal (avec un `HOME` temporaire, `gh` n'est pas authentifié et sort en code 4).
*EN: run compare_refs --run with the real HOME so gh is authenticated.*

## Direct (serveur `rover live`, kit `tools/server/`)

Cible : Ubuntu 24.04 LTS x86-64 (Contabo Cloud VPS 4 : 4 vCPU, 8 Go ; le kit n'est pas lié à un hébergeur). Tout se lance en root sur le serveur ; sur le Mac, les essais passent par `--root DIR` (actions système simulées).

1. Installer : `sudo tools/server/install.sh --domain EXEMPLE.fr --pages-origin https://LOGIN.github.io --repo LOGIN/DEPOT --sha COMMIT`. Toujours d'abord `--dry-run` : il liste les étapes S1 à S11 sans rien toucher (il annonce moins de changements que l'application réelle, ex. 31 contre 43 : les sous-dossiers ne sont comptés qu'une fois leurs parents créés). Comptes : `sol0` (moteur et publication), `sol0web` (web), groupe `sol0stream`. Relancé, le script rend « 0 changement ». `/etc/sol0/live.toml` n'est créé qu'une fois (`publish = "off"`) : l'utilisateur le modifie ensuite.
2. Jeton : `sudo sol0ctl token set` (saisie masquée, fichier en 0600 dans un dossier 0700 ; l'adresse noreply du propriétaire est lue par `GET /user`). Contrôle : `sudo sol0ctl token check`. Le jeton n'est jamais dans argv, l'environnement, les journaux ni le dépôt.
3. DNS : `A live -> IPv4` (et `AAAA` si IPv6), TTL 300. Caddy obtient seul le certificat. Contrôle : `curl -sSI https://live.EXEMPLE.fr/health`, ou `tools/server/healthcheck.sh`.
4. État : `sol0ctl status` (services, santé, cause), `sol0ctl logs`, `sol0ctl stop|start`.
5. Annuler une installation : `sudo tools/server/rollback.sh <UTC>` (horodatage dans `/var/backups/sol0/`) rend les fichiers, liens et dossiers. Paquets, utilisateurs, pare-feu et services ne sont pas défaits (notés « note » dans `undo.log`).
6. Redémarrage : `sol0-reboot.timer` (15 min) ne redémarre que si `/var/run/reboot-required` existe, le moteur est en phase `idle`, le créneau suivant est à plus de 60 s et aucune publication n'est en attente.
7. SSH par clé seule : posé seulement si `/root/.ssh/authorized_keys` n'est pas vide et si `sshd -t` passe (sinon l'étape est ignorée, avec message).

8. **Naissance : le moteur est retenu.** `install.sh` ne démarre jamais `rover-live` : tant que `/var/lib/sol0/live/birth.json` n'existe pas, un tiroir systemd `rover-live.service.d/00-hold-until-golive.conf` (`ExecCondition=/bin/false`) le garde activé mais arrêté. Seule commande qui le libère, lancée par Diapason avec l'accord de l'utilisateur : `sudo sol0ctl birth --at AAAA-MM-JJTHH:MM:SSZ` (UTC, entre 5 min dans le passé et 1 h dans le futur ; refuse si déjà né, si l'horloge n'est pas synchronisée ou si la date est mal formée ; écrit `birth.json`, retire le tiroir, démarre le moteur). `sol0ctl start` ne démarre que le web tant que le tiroir existe.
9. Horloge : l'installation active `systemd-timesyncd`/NTP ; `rover-live` refuse de démarrer si l'horloge n'est pas synchronisée (`tools/server/ntp_check.sh`, `ExecStartPre`), `sol0ctl status` l'indique.
10. Durcissement (audit du direct) : dossier du flux en `2750 sol0:sol0stream` (setgid : le web lit les fichiers du moteur) ; Caddy sans API d'administration (`admin off`, donc `systemctl restart caddy` et non `reload`, coupure brève) et rechargé dès que le Caddyfile change ; `sol0ctl token set` n'accepte que les jetons à grain fin `github_pat_` ; `X-Forwarded-For` remplacé par Caddy, délais d'en-tête ; SSH : `MaxAuthTries 3`, `LoginGraceTime 30`, pas de X11 ni de redirection TCP, `ufw limit 22/tcp`. Restent hors kit : permissions du jeton (Contents seulement, jamais Workflows), protection de `main` (audit S-4), unité de publication séparée (S-5).

Non vérifié ici (à faire en L4 sur le vrai serveur) : `systemd-analyze verify`, `caddy validate`, `ufw`, `apt`, nom d'origine du dépôt apt de Caddy pour les mises à jour automatiques. `sol0ctl update|rollback-release|restore|adopt-remote|force-local` : à fournir en L4/L5.
*EN: Direct = install kit in tools/server (dry run, idempotent, rollback); token via `sol0ctl token set`; systemd/Caddy/ufw validated only in L4 on the real server.*
