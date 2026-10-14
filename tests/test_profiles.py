import pytest
import urllib3
from selenium.common.exceptions import WebDriverException

from fb_modular.browser import js
from fb_modular.core.models import Status
from fb_modular.extractors import profiles

FRIEND = {'friend_id': 'samia.rakoto', 'display_name': 'Samia Rakoto',
          'profile_url': 'https://www.facebook.com/samia.rakoto', 'photo_url': 'https://scontent.x/list.jpg'}


class FakeProfileDriver:
    def __init__(self, get_error=None, url='https://www.facebook.com/samia.rakoto', info=None,
                 posts=None, block=None):
        self.get_error, self.current_url = get_error, url
        self.info = info if info is not None else {'bio': 'Habite à Tana', 'date': '', 'photo': 'https://scontent.x/p.jpg', 'gone': False}
        self.batches = [posts or []]
        self.block = block or {'login': False, 'blocked': False}

    def get(self, url):
        if self.get_error:
            raise self.get_error

    def execute_script(self, code, *args):
        if code is js.JS_BLOCK_CHECK:
            return self.block
        if code is js.JS_DIALOGUES:
            return []
        if code is js.JS_PROFILE_INFOS:
            return self.info
        if code is js.JS_POSTS:
            return self.batches.pop(0) if self.batches else []
        if isinstance(code, str) and 'querySelectorAll' in code and 'article' in code and 'length' in code:
            return len(self.batches[0]) if self.batches else 0
        if isinstance(code, str) and 'scrollY' in code and code.strip().startswith('return window.scrollY'):
            return 0
        return True


@pytest.fixture(autouse=True)
def static_page(monkeypatch):
    monkeypatch.setattr(profiles, 'scroll_window_and_wait', lambda *a, **k: False)


def scrape(driver, settings, logger, **features):
    s = settings.with_features(comments=False, reactions=False, **features)
    return profiles.scrape_friend_profile(driver, FRIEND, s, logger, own_photo='https://scontent.x/own.jpg')


def test_real_read_timeout_from_the_log_is_a_network_error_not_a_zero_post_profile(settings, logger):
    """Le journal : ReadTimeoutError après 120 s => la v1 enregistrait 'SUSPECT, 0 post'."""
    err = urllib3.exceptions.ReadTimeoutError(None, '/session/x/url', 'Read timed out. (read timeout=120)')
    result = scrape(FakeProfileDriver(get_error=err), settings, logger)
    assert result.status is Status.NETWORK and not result.writable


def test_chrome_net_error_from_the_log_is_a_network_error(settings, logger):
    err = WebDriverException('Message: unknown error: net::ERR_CONNECTION_TIMED_OUT\n  (Session info: chrome=155)')
    result = scrape(FakeProfileDriver(get_error=err), settings, logger)
    assert result.status is Status.NETWORK and not result.writable


def test_closed_browser(settings, logger):
    result = scrape(FakeProfileDriver(get_error=WebDriverException('invalid session id')), settings, logger)
    assert result.status is Status.BROWSER_CLOSED


def test_checkpoint_url_is_blocked(settings, logger):
    result = scrape(FakeProfileDriver(url='https://www.facebook.com/checkpoint/1501092823525282/'), settings, logger)
    assert result.status is Status.BLOCKED and not result.writable


def test_login_form_is_blocked(settings, logger):
    result = scrape(FakeProfileDriver(block={'login': True, 'blocked': False}), settings, logger)
    assert result.status is Status.BLOCKED


def test_unexpected_error_is_status_error(settings, logger):
    result = scrape(FakeProfileDriver(get_error=RuntimeError('boom')), settings, logger)
    assert result.status is Status.ERROR and 'boom' in result.error and not result.writable


def test_unavailable_profile_is_writable(settings, logger):
    info = {'bio': '', 'date': '', 'photo': '', 'gone': True}
    result = scrape(FakeProfileDriver(info=info), settings, logger)
    assert result.status is Status.UNAVAILABLE and result.writable


def test_ok_profile_collects_posts_and_profile_photo(settings, logger):
    posts = [[object(), 'k1', 'Premier post suffisamment long', '12 oct', None],
             [object(), 'k2', 'Deuxième post suffisamment long', '', None],
             [object(), 'k1', 'Premier post suffisamment long', '12 oct', None]]   # doublon de clé
    result = scrape(FakeProfileDriver(posts=posts), settings, logger)
    assert result.status is Status.OK and result.profile.post_count == 2
    assert result.profile.photo_url == 'https://scontent.x/p.jpg'
    assert result.photos and result.photos[0]['photo_type'] == 'PROFIL'
    assert result.profile.bio == 'Habite à Tana'


def test_photo_equal_to_my_own_is_dropped(settings, logger):
    info = {'bio': '', 'date': '', 'photo': 'https://scontent.x/own.jpg?oh=zzz', 'gone': False}
    result = scrape(FakeProfileDriver(info=info), settings, logger)
    assert result.profile.photo_url == '' and not result.photos


def test_photo_falls_back_to_the_friend_list_photo(settings, logger):
    info = {'bio': '', 'date': '', 'photo': '', 'gone': False}
    result = scrape(FakeProfileDriver(info=info), settings, logger)
    assert result.profile.photo_url == 'https://scontent.x/list.jpg'


def test_post_limit_still_records_the_photo(settings, logger):
    """Régression : la v1 sortait avant d'écrire la photo quand la limite de posts était atteinte."""
    posts = [[object(), f'k{i}', f'Post numéro {i} suffisamment long', '', None] for i in range(10)]
    s = settings.with_limits(max_posts_per_friend=3)
    result = scrape(FakeProfileDriver(posts=posts), s, logger)
    assert result.profile.post_count == 3 and result.photos


def test_zero_posts_with_visible_publications_is_an_error_not_a_fake_zero(settings, logger, tmp_path):
    """Régression : des posts affichés mais non extraits étaient enregistrés comme « 0 post »."""
    class Broken(FakeProfileDriver):
        def execute_script(self, code, *args):
            if code is js.JS_DIAG_POSTS:
                return {'articles': 4, 'permalinks': 6, 'feed_units': 0, 'story_message': 0,
                        'old_message': 0}
            return super().execute_script(code, *args)

        def save_screenshot(self, path):
            open(path, 'wb').close()

    result = scrape(Broken(), settings, logger)
    assert result.status is Status.ERROR and not result.writable
    assert 'diagnostics' in result.error
    assert list(settings.paths.debug_dir.glob('profile_*.json'))


def test_zero_posts_on_a_really_empty_profile_stays_ok(settings, logger):
    class Empty(FakeProfileDriver):
        def execute_script(self, code, *args):
            if code is js.JS_DIAG_POSTS:
                return {'articles': 0, 'permalinks': 0, 'feed_units': 0, 'story_message': 0,
                        'old_message': 0}
            return super().execute_script(code, *args)

        def save_screenshot(self, path):
            open(path, 'wb').close()

    result = scrape(Empty(), settings, logger)
    assert result.status is Status.OK and result.profile.post_count == 0
