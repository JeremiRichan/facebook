"""Modèles de données (schéma canonique) pour le scraping Facebook."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now().isoformat()


class Status(str, Enum):
    OK = 'ok'
    UNAVAILABLE = 'unavailable'      # profil supprimé / inaccessible : enregistré, pas re-tenté
    ERROR = 'error'                  # erreur inattendue : NON enregistré, re-tenté
    NETWORK = 'network'              # coupure réseau : NON enregistré, re-tenté avec attente
    BLOCKED = 'blocked'              # checkpoint / login : arrêt du programme
    BROWSER_CLOSED = 'browser_closed'


@dataclass
class Friend:
    friend_id: str
    display_name: str
    profile_url: str
    photo_url: str = ''
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class ProfileData:
    friend_id: str
    display_name: str
    profile_url: str
    photo_url: str = ''
    account_created: str = 'Inconnue'
    bio: str = ''
    post_count: int = 0
    comment_count: int = 0
    reaction_count: int = 0          # total de réactions cumulées sur les posts collectés
    comments_collected: bool = True  # False si --no-comments (évite de pénaliser le score)
    reactions_collected: bool = True
    error_message: Optional[str] = None
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class ReactionSummary:
    reaction_id: str
    post_id: str
    reaction_type: str
    count: int
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class ReactorData:
    """Une personne qui a réagi à un post (nom + lien de profil + type de réaction)."""

    post_id: str
    owner_id: str            # propriétaire du post (l'ami scrapé)
    reactor_id: str
    reactor_name: str
    reactor_url: str
    reaction_type: str       # like, love, haha... ou 'unknown' si l'onglet par type est absent
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class CommentData:
    comment_id: str
    post_id: str
    owner_id: str
    text_content: str
    author_name: str
    date_text: str = ''
    parent_comment_id: Optional[str] = None
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class PostData:
    post_id: str
    owner_id: str
    text_content: str
    date_text: str = ''
    reactions_total: int = 0
    comments_total: int = 0
    reactions_detail: List[Dict[str, Any]] = field(default_factory=list)
    extracted_at: str = field(default_factory=utc_now_iso)


@dataclass
class ScoreResult:
    score_fake: float
    verdict: str
    signals: str


@dataclass
class ScrapeResult:
    """Résultat complet du scraping d'un ami.

    Rien n'est écrit sur disque tant que status n'est pas OK ou UNAVAILABLE.
    """

    profile: ProfileData
    status: Status = Status.OK
    posts: List[PostData] = field(default_factory=list)
    comments: List[CommentData] = field(default_factory=list)
    reactions: List[ReactionSummary] = field(default_factory=list)
    reactors: List[ReactorData] = field(default_factory=list)
    photos: List[Dict[str, str]] = field(default_factory=list)
    error: str = ''

    @property
    def writable(self) -> bool:
        return self.status in (Status.OK, Status.UNAVAILABLE)
