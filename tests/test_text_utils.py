import pytest

from fb_modular.core.text_utils import (
    extract_leading_number, is_notification_link, is_valid_display_name, is_valid_stored_id,
    normalise_reaction_label, strip_query,
)


@pytest.mark.parametrize('name', ['Samia Rakoto', 'Amina', 'Jamila', 'Rami',
                                  'Randrianamihaja Tsiory', 'Jean Paul', 'Vero Hanitry Ny Aina'])
def test_real_names_are_accepted(name):
    """Régression : la v1 rejetait tout nom contenant « ami »."""
    assert is_valid_display_name(name)


@pytest.mark.parametrize('name', [
    '30 mutual friends', '5 amis en commun', 'Friends', 'Messages', '',
    'UnreadRaïssa Ainamalala mentioned you and other followers in a comment.27m',
    'You have memories to look back on today.1h',
    'Make progress this week. Follow a few steps to grow your audience.3h',
])
def test_noise_and_navigation_are_rejected(name):
    assert not is_valid_display_name(name)


@pytest.mark.parametrize('text,expected', [
    ('245', 245), ('Tous, 245', 245), ("J'aime 1 245", 1245), ('1,2 k', 1200),
    ('3 M', 3_000_000), ('2.5K', 2500), ('2,359', 2359), ('', 0), ('aucun', 0),
])
def test_extract_leading_number(text, expected):
    assert extract_leading_number(text) == expected


def test_notification_links():
    assert is_notification_link('https://x/permalink.php?story_fbid=1&notif_id=2&ref=notif')
    assert is_notification_link('https://x/stories/1/?source=notification&notif_t=reactions')
    assert not is_notification_link('https://www.facebook.com/jean.dupont')


def test_stored_id_validation():
    assert is_valid_stored_id('__moi__') and is_valid_stored_id('samia.rakoto')
    assert is_valid_stored_id('1000123')
    assert not is_valid_stored_id('permalink.php')
    assert not is_valid_stored_id('onthisday')
    assert not is_valid_stored_id('professional_dashboard')


def test_reaction_labels():
    assert normalise_reaction_label("J’aime 12") == 'like'
    assert normalise_reaction_label('J\'adore 3') == 'love'
    assert normalise_reaction_label('Tous 245') is None


def test_strip_query():
    assert strip_query('https://cdn/x.jpg?oh=1&oe=2') == 'https://cdn/x.jpg'
