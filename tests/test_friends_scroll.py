import pytest

from fb_modular.browser import js
from fb_modular.extractors.friends import extract_all_friends


class FakeListDriver:
    """Simule la colonne d'amis : défilement interne + chargement paresseux par paquets de 30."""

    def __init__(self, total_loadable, announced='', first_page=30, notifications=True):
        self.total, self.announced = total_loadable, announced
        self.loaded, self.top, self.client = first_page, 0, 600
        self.row_h, self.notifications = 100, notifications
        self.current_url, self.scroll_calls, self.screens = 'https://www.facebook.com/', 0, []

    def get(self, url):
        self.current_url = url

    def save_screenshot(self, path):
        self.screens.append(path)
        open(path, 'wb').write(b'png')
        return True

    @property
    def height(self):
        return self.loaded * self.row_h

    def execute_script(self, code, *args):
        if code is js.JS_BLOCK_CHECK:
            return {'login': False, 'blocked': False}
        if code is js.JS_DIALOGUES:
            return []
        if code is js.JS_EXPECTED_TOTAL:
            return self.announced
        if code is js.JS_DIAG_ANCHORS:
            return [{'href': 'x'}]
        if code is js.JS_FRIEND_ANCHORS:
            rows = [[f'https://web.facebook.com/user.{n}', f'Ami Numero{n}', '', 'https://scontent.x/p.jpg']
                    for n in range(self.loaded)]
            if self.notifications:
                rows.append(['https://web.facebook.com/notifications/', '', '', ''])
                rows.append(['https://web.facebook.com/permalink.php?notif_id=1', 'Unread X mentioned you', '', ''])
            return rows
        if code is js.JS_FRIEND_SCROLL:
            delta = args[0]
            if delta:
                self.scroll_calls += 1
                self.top = min(self.top + delta, max(self.height - self.client, 0))
                if self.top + self.client >= self.height - 10 and self.loaded < self.total:
                    self.loaded = min(self.loaded + 30, self.total)     # lazy load
            return ['el', self.top, self.height, self.client]
        return True      # attentes de chargement (readyState, main...)


def friends_of(driver, settings, logger, **limits):
    s = settings.with_limits(scroll_pause_seconds=0.01, **limits)
    return extract_all_friends(driver, s, logger)


def test_collects_all_friends_with_lazy_loading_and_stops_at_announced_total(settings, logger):
    driver = FakeListDriver(total_loadable=250, announced='250')
    friends = friends_of(driver, settings, logger)
    assert len(friends) == 250
    assert friends[0]['friend_id'] == 'user.0' and friends[0]['profile_url'].endswith('/user.0')
    assert not any('notif' in f['profile_url'] or f['friend_id'] == 'permalink.php' for f in friends)


def test_stops_by_itself_when_the_list_ends_without_announced_total(settings, logger):
    driver = FakeListDriver(total_loadable=100, announced='')
    friends = friends_of(driver, settings, logger)
    assert len(friends) == 100
    assert driver.scroll_calls < 60          # ne boucle pas indéfiniment


def test_max_scan_truncates(settings, logger):
    friends = friends_of(FakeListDriver(500, '500'), settings, logger, max_friends_total=70)
    assert len(friends) == 70


def test_no_friends_dumps_diagnostics_and_returns_empty(settings, logger):
    driver = FakeListDriver(total_loadable=0, first_page=0)
    assert friends_of(driver, settings, logger) == []
    assert (settings.paths.debug_dir / 'friends_anchors.json').exists()
    assert driver.screens


def test_blocked_page_raises(settings, logger):
    from fb_modular.core.errors import BlockedError

    class Blocked(FakeListDriver):
        def execute_script(self, code, *args):
            if code is js.JS_BLOCK_CHECK:
                return {'login': True, 'blocked': False}
            return super().execute_script(code, *args)

    with pytest.raises(BlockedError):
        friends_of(Blocked(10), settings, logger)
