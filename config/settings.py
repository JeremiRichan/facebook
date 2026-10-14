"""Configuration centralisée du scraper Facebook."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List

from ..core.text_utils import DEFAULT_FORBIDDEN_IDS


@dataclass(frozen=True)
class Paths:
    base_dir: Path
    profile_dir: Path
    users_csv: Path
    relations_csv: Path
    posts_csv: Path
    comments_csv: Path
    photos_csv: Path
    reactions_csv: Path
    reactors_csv: Path
    progress_csv: Path
    friends_cache: Path
    debug_dir: Path
    log_file: Path


@dataclass(frozen=True)
class ScrapingLimits:
    # Volume
    max_friends_total: int = 2600          # nb max d'amis à EXTRAIRE de la liste
    friends_per_run: int = 0               # nb max d'amis à TRAITER sur ce lancement (0 = tous)
    max_posts_per_friend: int = 20
    max_comments_per_post: int = 300
    max_reactors_per_post: int = 200       # personnes lues par post (option --reactors)
    # Parcours
    max_scrolls_friends: int = 600
    friends_stall_limit: int = 6
    max_scrolls_profile: int = 50
    profile_stall_limit: int = 14
    max_comment_passes: int = 40
    scroll_pause_seconds: float = 2.5
    scroll_step_pixels: int = 900
    # Rythme
    pause_min: float = 8.0
    pause_max: float = 15.0
    batch_size: int = 3
    batch_pause: float = 30.0
    # Robustesse
    retries: int = 1                       # nouvelles tentatives sur erreur inattendue
    max_consecutive_failures: int = 3      # échecs d'affilée avant arrêt
    max_network_retries: int = 6           # tentatives sur coupure réseau (attente exponentielle)
    network_backoff_base: float = 30.0
    network_backoff_max: float = 600.0
    friends_cache_hours: float = 72.0      # durée de validité du cache de la liste d'amis


@dataclass(frozen=True)
class Features:
    comments: bool = True
    reactions: bool = True
    reactors: bool = True                  # noms de ceux qui ont réagi (--no-reactors pour désactiver)
    refresh_friends: bool = False
    retry_zero_posts: bool = False
    headless: bool = False
    no_sandbox: bool = False
    chrome_version: int | None = None      # None = détection automatique
    verbose: bool = False


@dataclass(frozen=True)
class KeywordSets:
    """Mots-clés / expressions multi-langues pour reconnaître l'interface Facebook."""

    forbidden_ids: set = field(default_factory=lambda: set(DEFAULT_FORBIDDEN_IDS))

    reaction_exclusion_words: List[str] = field(default_factory=lambda: [
        'commentaire', 'comment', 'partage', 'share', 'écrire', 'write', 'répondre', 'reply',
        'comentario', 'compartir', 'kommentar', 'teilen', 'commento', 'condividi',
    ])

    # Préfixes de l'aria-label d'un COMMENTAIRE (ou d'une réponse) ; exclut le post lui-même.
    comment_prefixes: List[str] = field(default_factory=lambda: [
        'commentaire de', 'comment by', 'commented', 'a commenté', 'comentario de',
        'kommentar von', 'commento di', 'comentário de', 'comment from',
        'réponse de', 'reply by', 'reply from', 'replied',
    ])

    reaction_type_regex: str = (
        r"j.aime|like|love|adore|haha|wow|waouh|triste|sad|grrr|angry|colère|soutien|care|"
        r"réaction|reaction|me gusta|me encanta"
    )
    who_reacted_regex: str = (
        r"voir qui a réagi|see who reacted|toutes les réactions|all reactions|"
        r"ver quién reaccionó"
    )
    # Compteur cliquable « 12 commentaires » (ouvre le post quand il n'a pas de lien permanent).
    comment_count_regex: str = (
        r"\d[\d.,\s\u00a0]*[kKmM]?\s*(?:comments?|commentaires?|comentarios?|kommentare?|commenti|"
        r"coment[áa]rios?)"
    )
    # Bouton de tri "Plus pertinents" (on bascule vers "Tous les commentaires").
    sort_button_regex: str = (
        r"plus\s+pertinents?|most\s+relevant|top\s+comments|commentaires\s+principaux|"
        r"most\s+popular|plus\s+populaires|más\s+relevantes|più\s+rilevanti|"
        r"mais\s+relevantes|relevanteste"
    )
    all_comments_regex: str = (
        r"tous\s+les\s+commentaires|all\s+comments|todos\s+los\s+comentarios|"
        r"alle\s+kommentare|tutti\s+i\s+commenti|todos\s+os\s+coment"
    )
    expansion_regex: str = (
        r"voir\s+plus|view\s+more|see\s+more|load\s+more|voir\s+les?\s+r[ée]ponse|"
        r"view\s+(?:all\s+)?\d*\s*repl|\d+\s+r[ée]ponse|\d+\s+repl|afficher\s+plus|show\s+more|"
        r"voir\s+les?\s+commentaires|view\s+(?:more\s+)?comments|voir\s+\d+\s+(?:autres|commentaires)|"
        r"ver\s+más|mehr\s+anzeigen|mostra\s+altro"
    )
    # Lignes d'« intro » d'un profil (emploi, ville, études, situation...).
    bio_regex: str = (
        r"^(travaille|a travaillé|étudie|a étudié|habite|vit à|vit en|originaire|né le|né à|"
        r"célibataire|marié|en couple|en relation|fiancé|divorcé|veuf|veuve|"
        r"works at|worked at|studies|studied at|lives in|from |born|single|married|"
        r"in a relationship|engaged|went to|suivi par|followed by|\d+\s+(followers|abonnés))"
    )
    joined_regex: str = (
        r"(?:Rejoint|A rejoint|Joined|Se unió|Beigetreten|Si è unito)\s+Facebook[^\n]*"
    )
    unavailable_regex: str = (
        r"(Ce contenu n.est pas disponible|This content isn.t available|"
        r"Cette page n.est pas disponible|This page isn.t available|"
        r"Este contenido no está disponible)"
    )


@dataclass(frozen=True)
class ScraperSettings:
    paths: Paths
    limits: ScrapingLimits = field(default_factory=ScrapingLimits)
    keywords: KeywordSets = field(default_factory=KeywordSets)
    features: Features = field(default_factory=Features)

    @classmethod
    def from_base_dir(cls, base_dir: Path | None = None) -> 'ScraperSettings':
        root = Path(base_dir).expanduser().resolve() if base_dir else Path(__file__).resolve().parents[2]
        profile_name = os.getenv('FB_PROFILE_DIR', 'Facebook_Profile')
        paths = Paths(
            base_dir=root,
            profile_dir=root / profile_name,
            users_csv=root / 'Facebook_User.csv',
            relations_csv=root / 'Facebook_Relation.csv',
            posts_csv=root / 'Facebook_Post.csv',
            comments_csv=root / 'Facebook_Comment.csv',
            photos_csv=root / 'Facebook_Photo.csv',
            reactions_csv=root / 'Facebook_Reaction.csv',
            reactors_csv=root / 'Facebook_Reactor.csv',
            progress_csv=root / 'Facebook_scraping.csv',
            friends_cache=root / 'Facebook_Amis_cache.json',
            debug_dir=root / 'diagnostics',
            log_file=root / 'scraping.log',
        )
        return cls(paths=paths)

    def with_limits(self, **changes) -> 'ScraperSettings':
        return replace(self, limits=replace(self.limits, **changes))

    def with_features(self, **changes) -> 'ScraperSettings':
        return replace(self, features=replace(self.features, **changes))
