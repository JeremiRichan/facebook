"""Score 'fake' d'un profil (heuristique simple, à ne pas prendre pour une preuve)."""

from __future__ import annotations

import re
from datetime import datetime

from .models import ProfileData, ScoreResult

THRESHOLD_FAKE = 0.60
THRESHOLD_SUSPECT = 0.30


def compute_fake_score(profile: ProfileData, now: datetime | None = None) -> ScoreResult:
    """Chaque signal a un poids ; le maximum théorique dépasse 0.60, donc FAKE_PROBABLE
    est atteignable (dans la v1 le maximum était 0.55).

    - Une date de création inconnue ne pénalise plus (elle est presque toujours inconnue).
    - Les signaux commentaires/réactions ne comptent que si ces données ont été collectées.
    """
    now = now or datetime.now()
    score = 0.0
    signals: list[str] = []
    posts = profile.post_count

    if not profile.photo_url:
        score += 0.25
        signals.append('pas_photo')
    if posts == 0:
        score += 0.25
        signals.append('zero_post')
    elif posts < 3:
        score += 0.10
        signals.append('peu_posts')
    if not profile.bio:
        score += 0.10
        signals.append('bio_vide')
    if posts > 0 and profile.comments_collected and profile.comment_count == 0:
        score += 0.10
        signals.append('zero_commentaires')
    if posts > 0 and profile.reactions_collected and profile.reaction_count == 0:
        score += 0.10
        signals.append('zero_reactions')
    year = re.search(r'(?:19|20)\d{2}', profile.account_created or '')
    if year and int(year.group(0)) >= now.year - 1:
        score += 0.15
        signals.append('compte_recent')

    final = min(round(score, 3), 1.0)
    if final >= THRESHOLD_FAKE:
        verdict = 'FAKE_PROBABLE'
    elif final >= THRESHOLD_SUSPECT:
        verdict = 'SUSPECT'
    else:
        verdict = 'REEL'
    return ScoreResult(score_fake=final, verdict=verdict,
                       signals=' | '.join(signals) if signals else 'aucun')


def unavailable_score() -> ScoreResult:
    return ScoreResult(score_fake=0.0, verdict='INDISPONIBLE', signals='profil_indisponible')
