from datetime import datetime

from fb_modular.core.models import ProfileData
from fb_modular.core.scoring import compute_fake_score


def profile(**kw):
    base = dict(friend_id='a', display_name='A', profile_url='u', photo_url='http://p', bio='b',
                post_count=10, comment_count=5, reaction_count=20)
    base.update(kw)
    return ProfileData(**base)


def test_active_profile_is_real():
    assert compute_fake_score(profile()).verdict == 'REEL'


def test_empty_profile_reaches_fake_probable():
    """Régression : le maximum de la v1 était 0.55 (< seuil 0.60)."""
    result = compute_fake_score(profile(photo_url='', bio='', post_count=0))
    assert result.score_fake >= 0.60 and result.verdict == 'FAKE_PROBABLE'


def test_unknown_creation_date_no_longer_penalises():
    assert 'date_inconnue' not in compute_fake_score(profile(account_created='Inconnue')).signals


def test_recent_account_is_a_signal():
    now = datetime(2026, 10, 13)
    result = compute_fake_score(profile(account_created='Rejoint Facebook en mars 2026'), now)
    assert 'compte_recent' in result.signals


def test_disabled_collection_is_not_penalised():
    result = compute_fake_score(profile(comment_count=0, reaction_count=0,
                                        comments_collected=False, reactions_collected=False))
    assert result.signals == 'aucun'


def test_silent_posts_are_penalised_when_collected():
    result = compute_fake_score(profile(comment_count=0, reaction_count=0))
    assert 'zero_commentaires' in result.signals and 'zero_reactions' in result.signals
