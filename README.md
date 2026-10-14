# Scraper Facebook modulaire — v2

Usage pédagogique : analyse du réseau de **vos propres amis** (CSV → Neo4j).
Le schéma des CSV est identique à la v1 : `neo4j_loader.py` et `fix_post.py` fonctionnent sans changement.

## Installation
```bash
pip install -r requirements.txt          # + Google Chrome installé
pip install -r requirements-dev.txt      # (optionnel) tests
```

## Lancement
Depuis le dossier qui **contient** `fb_modular/` (par ex. `~/facebook`) :
```bash
python -m fb_modular --limit 5           # TEST sur 5 amis d'abord
python -m fb_modular                     # tous les amis (reprise automatique)
python -m fb_modular --no-comments --no-reactions   # mode rapide
python -m fb_modular --reactors --limit 3 --verbose  # + noms de ceux qui ont réagi (test)
python -m fb_modular clean --dry-run     # voir ce qui serait purgé des CSV
python -m fb_modular clean               # purger les faux amis / échecs (sauvegardes .bak-<date>)
python -m fb_modular --retry-zero-posts  # re-scraper les amis enregistrés à 0 post
```
Le premier lancement ouvre Chrome : connectez-vous, puis appuyez sur ENTRÉE. La session est
conservée dans `Facebook_Profile/` ; les lancements suivants n'ont plus rien à demander.

Options utiles : `--limit N` (amis traités sur ce lancement), `--max-posts`, `--max-comments`,
`--pause-min/--pause-max`, `--refresh-friends`, `--chrome-version`, `--verbose`. `--help` pour tout.

## Ce qui a changé par rapport à la v1 / première version modulaire
| Problème | Correction |
|---|---|
| Les notifications (`permalink.php`, `onthisday`…) étaient prises pour des amis | Liens de la cloche/du bandeau exclus ; whitelist stricte d'URL de profil |
| Les pseudos avec un point (`samia.rakoto`) étaient **tous rejetés** | Règle d'ID corrigée (seules les extensions de fichier sont refusées) |
| La liste d'amis est une colonne à ascenseur interne : `window.scrollBy` ne défilait rien | On fait défiler le conteneur de la liste ; total annoncé (« 2,359 friends ») lu pour vérifier la complétude |
| Un échec réseau / checkpoint était enregistré comme « SUSPECT, 0 post » et marqué traité | Écriture **uniquement** si le scraping a réussi ; sinon re-tentative, backoff réseau, arrêt propre en cas de blocage |
| `--max-friends 5` limitait l'*extraction* (donc rien de neuf à la reprise) | `--limit` compte les amis *traités* ; `--max-friends` reste un alias |
| `driver.get` bloquait 120 s | `page_load_strategy=eager`, timeouts, `window.stop()` |
| ~45 s pour lire 170 liens (un appel Selenium par attribut) | Extraction par snippets JS : un seul aller-retour |
| Photo de profil : risque de prendre la **vôtre** (barre du haut) | Bandeau exclu + comparaison avec votre photo |
| Texte d'un commentaire pollué par ses réponses imbriquées | Lecture limitée à l'élément propre (`own()`) |
| `FAKE_PROBABLE` inatteignable (max 0,55 < 0,60) | Nouvelle pondération ; date inconnue non pénalisée |
| Total de réactions = somme des types, `1,2 k` lu comme 12 | Onglet « Tous » + gestion k/M |
| Liste d'amis rescannée à chaque lancement | Cache `Facebook_Amis_cache.json` (72 h) |

## Pauses aléatoires et comportement « humain »
Rien de ce que faisait la v1 n'a disparu ; les clics et pauses sont même plus variables.

| Mécanisme | Détail | Réglage |
|---|---|---|
| Pause entre deux amis | aléatoire 8–15 s | `--pause-min` / `--pause-max` |
| Longue pause | 30 s + 0–10 s tous les 3 amis | `--batch-size` / `--batch-pause` |
| Après chargement d'un profil | aléatoire 1,5–2,5 s | — |
| Défilement du profil | pas de 900 px ± 80 aléatoire, attente adaptative | `--scroll-step` (code) |
| Défilement de la liste d'amis | pas × (0,7 à 1,0) aléatoire | — |
| Commentaires, réactions, onglets | toutes les pauses ±40 % (`human_sleep`) | — |
| Clics | **clics Selenium un par un** (3 boutons « Voir plus » max par passe), jamais de rafale JavaScript | — |
| Session | profil Chrome persistant (`Facebook_Profile/`), pas de reconnexion | — |
| `--disable-blink-features=AutomationControlled` | rétabli | — |
| `navigator.webdriver` masqué à chaque page | rétabli (en plus de ce que fait undetected-chromedriver) | — |
| Après un échec | attente 15–25 s ; coupure réseau : 30 s → 10 min (exponentiel) | `--retries` |
| **Arrêt de sécurité** | checkpoint, page de connexion, message de limitation, ou 3 échecs d'affilée | `--max-failures` |

**Ce que cela ne garantit pas** : éviter un blocage. Facebook détecte surtout le *volume* et la
*régularité* sur la durée, pas seulement le rythme d'une action. Le plus efficace reste de travailler
par petites sessions (ex. `--limit 30` par jour) plutôt que 2 000+ amis d'un coup. Il n'y a pas de
mouvements de souris simulés, de quota journalier automatique ni de plage horaire : ils ne sont pas
implémentés. L'automatisation reste contraire aux conditions d'utilisation de Facebook.

## Qui a réagi (activé par défaut, `--no-reactors` pour désactiver)
Les **compteurs** par type sont écrits dans `Facebook_Reaction.csv`. Par défaut, le script ouvre aussi chaque onglet de la fenêtre des réactions (J'aime, J'adore…), fait défiler la
liste et écrit **`Facebook_Reactor.csv`** :

| id_post | id_reacteur | nom_reacteur | url_reacteur | type | extraction_date |
|---|---|---|---|---|---|

- `--max-reactors N` : personnes lues par post (défaut 200).
- Une personne n'a qu'une réaction : la première trouvée gagne (évite de reclasser une ligne
  résiduelle de l'onglet précédent). Sans onglets par type, le type vaut `unknown`.
- C'est **plus lent** (plusieurs clics et défilements par post) et **plus exposé** : testez d'abord
  avec `--limit 3`. Ce sont surtout des personnes qui ne sont pas vos amis : données personnelles de
  tiers, à pseudonymiser avant tout partage.
- `neo4j_loader.py` n'utilise pas encore ce fichier ; une relation `(:User)-[:REACTED_TO]->(:Post)` se
  construit directement depuis `id_reacteur` / `id_post`.

## Codes de sortie
`0` ok / interrompu / limite atteinte · `1` erreur · `2` connexion impossible · `3` blocage Facebook (checkpoint, limitation).

## Si « Aucun ami trouvé »
Facebook change régulièrement son HTML. Le programme écrit alors `diagnostics/friends_anchors.json`
et `diagnostics/friends_page.png` : ils décrivent la page réellement vue, ce qui permet d'ajuster
`browser/js.py` (`JS_FRIEND_ANCHORS`) sans deviner.

## Tests
```bash
python -m pytest fb_modular/tests -q
cd fb_modular/tests && npm install jsdom   # active en plus les tests des snippets JavaScript
```

## Limites connues (honnêteté)
- Les **sélecteurs Facebook** (posts, réactions, commentaires, « Rejoint Facebook ») sont des
  heuristiques validées sur du HTML simulé, **pas sur le vrai site** : un premier essai avec
  `--limit 3 --verbose` est indispensable. La date de création est souvent absente de la page.
- Facebook interdit l'automatisation : risque de checkpoint / limitation du compte. Pauses par
  défaut 8–15 s + 30 s tous les 3 amis ; ne les réduisez pas. Comptez **plusieurs minutes par ami**.
- **Réacteurs** : les onglets cachés dans le menu « Plus » de la fenêtre des réactions ne sont pas
  lus ; le total (`Tous`) reste exact. La lecture des noms dépend du HTML de Facebook comme le reste.
- **Commentaires** : la boucle s'arrête après `max_comment_passes` (40) ou 3 passes sans nouveauté ;
  un avertissement est écrit dans le log si un post a été coupé par cette limite.
- Le score « fake » est une heuristique simple : il classera des personnes réelles et discrètes
  comme suspectes. Ce n'est pas une preuve.
- Données personnelles d'autrui : pseudonymisez avant tout partage. Ne commitez jamais les CSV ni
  `Facebook_Profile/` (couverts par `.gitignore`).


## Correctifs « 0 post » / amis limités à 20 (octobre 2026)
| Symptôme du journal | Cause | Correction |
|---|---|---|
| `Facebook annonce 1 amis` puis `20 amis en 0 scrolls (2000 %)` | le total était lu sur un badge « 1 » suivi du libellé « Friends » à la ligne suivante | le nombre et le mot doivent être sur la même ligne ; un total inférieur aux amis déjà vus est ignoré |
| `0 posts` sur tous les profils | les posts sans texte (photo, reel, partage) ou à légende courte (< 15 caractères) étaient écartés ; sélecteur `story_message` absent | posts gardés dès qu'ils ont un permalien, un média ou du contenu ; repli par permaliens si la page n'a pas de `role="article"` |
| commentaires à 0 quand le post n'a pas de lien | aucune tentative d'ouverture | clic sur le compteur « N commentaires » en repli |
| pas de noms de réacteurs | option `--reactors` désactivée par défaut | activée par défaut (`--no-reactors` pour couper) |
| faux « 0 post » enregistré (score SUSPECT) | extraction ratée traitée comme profil vide | si la page affiche des posts mais qu'aucun n'est lu : statut ERREUR (non enregistré, re-tenté) + instantané dans `diagnostics/profile_<id>.json/.png` |
