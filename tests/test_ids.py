from fb_modular.core.text_utils import extract_facebook_id, normalise_facebook_url


def test_extract_profile_people_format():
    url = 'https://www.facebook.com/people/Jean-Dupont/100012345678901/'
    assert extract_facebook_id(url, set()) == '100012345678901'


def test_extract_profile_rejects_pfbid():
    assert extract_facebook_id('https://www.facebook.com/pfbid0abc123', set()) is None


def test_normalise_profile_php_preserves_id():
    url = 'https://web.facebook.com/profile.php?id=123456789'
    assert normalise_facebook_url(url) == 'https://www.facebook.com/profile.php?id=123456789'


def test_extract_rejects_permalink_and_notifications():
    assert extract_facebook_id('https://www.facebook.com/permalink.php', set()) is None
    assert extract_facebook_id('https://www.facebook.com/notifications/', set()) is None


def test_usernames_with_dots_are_accepted():
    """Régression : la v1 rejetait TOUS les pseudos contenant un point."""
    assert extract_facebook_id('https://www.facebook.com/samia.rakoto') == 'samia.rakoto'
    assert extract_facebook_id('https://web.facebook.com/john.doe.123/') == 'john.doe.123'


def test_numeric_profile_php():
    assert extract_facebook_id('https://www.facebook.com/profile.php?id=1000123') == '1000123'


def test_application_routes_from_the_real_log_are_rejected():
    for url in (
        'https://web.facebook.com/onthisday/?source=notification',
        'https://web.facebook.com/professional_dashboard/levels/?notif_id=1',
        'https://web.facebook.com/stories/210789320829754/UzpfSVNDOjE2/?source=notification',
        'https://web.facebook.com/permalink.php?story_fbid=pfbid04k&id=615&notif_id=17',
    ):
        assert extract_facebook_id(normalise_facebook_url(url)) is None


def test_post_links_of_a_friend_are_not_friend_ids():
    assert extract_facebook_id('https://www.facebook.com/jean.dupont/posts/pfbid02abc') is None


def test_foreign_hosts_are_rejected():
    assert normalise_facebook_url('https://notfacebook.com/x') == ''
    assert normalise_facebook_url('https://evil.com/?u=facebook.com') == ''
