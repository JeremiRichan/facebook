"""Boucle de lecture des commentaires, avec un faux navigateur qui simule la fenêtre d'un post :
chargement paresseux au défilement, boutons « Voir plus », fermeture de la fenêtre."""

import logging

import pytest
from selenium.common.exceptions import WebDriverException

from fb_modular.browser import js
from fb_modular.core.errors import BrowserClosedError
from fb_modular.extractors.posts import extract_comments

LOGGER = logging.getLogger('fb_test_comments')


class Clicker:
    """Faux élément : un clic Selenium (element.click()) déclenche l'action associée."""

    def __init__(self, action=lambda: None):
        self.action, self.clicks = action, 0

    def click(self):
        self.clicks += 1
        self.action()


class Permalink:
    def __init__(self, driver, opens=True, navigates=False):
        self.driver, self.opens, self.navigates = driver, opens, navigates

    def click(self):
        if self.opens:
            self.driver.dialog_open = True
        if self.navigates:
            self.driver.current_url = 'https://www.facebook.com/jean/posts/pfbid1'


class FakePostDriver:
    PAGE = 15                                   # commentaires ajoutés à chaque défilement

    def __init__(self, total, first=15, expanders=0, read_error=None):
        self.total, self.loaded, self.expanders = total, min(first, total), expanders
        self.read_error = read_error
        self.dialog_open, self.current_url = False, 'https://www.facebook.com/jean'
        self.scroll_calls = self.read_calls = self.closed = self.backs = self.expand_clicks = 0
        self.expand_args = ()

    def back(self):
        self.backs += 1
        self.current_url = 'https://www.facebook.com/jean'

    def execute_script(self, code, *args):
        if code is js.JS_DIALOGUES:
            return ['DIALOG'] if self.dialog_open else []
        if code is js.JS_FERMER:
            def close():
                self.dialog_open, self.closed = False, self.closed + 1
            return [Clicker(close)]
        if code is js.JS_TRI_PERTINENTS or code is js.JS_TRI_TOUS:
            return Clicker()
        if code is js.JS_EXPAND:
            if self.expanders > 0:
                self.expanders -= 1

                def more():
                    self.loaded = min(self.loaded + 10, self.total)    # « Voir plus » charge 10 de plus
                    self.expand_clicks += 1
                self.expand_args = args
                return [Clicker(more)]
            return []
        if code is js.JS_LIRE_COMMS:
            self.read_calls += 1
            if self.read_error:
                raise self.read_error
            return [[f'Auteur {n}', f'Commentaire numéro {n}', '3 h', f'Commentaire de Auteur {n}']
                    for n in range(self.loaded)]
        if code is js.JS_SCROLL_ZONE:
            self.scroll_calls += 1
            self.loaded = min(self.loaded + self.PAGE, self.total)  # chargement paresseux
            return self.loaded * 100
        return True


def run(driver, settings, **limits):
    s = settings.with_limits(**limits) if limits else settings
    link = Permalink(driver)
    return extract_comments(driver, link, 'post_1', 'jean.dupont', s.limits, s.keywords, LOGGER)


def test_reads_every_comment_through_lazy_loading(settings):
    driver = FakePostDriver(total=130)
    comments = run(driver, settings)
    assert len(comments) == 130
    assert [c.text_content for c in comments[:2]] == ['Commentaire numéro 0', 'Commentaire numéro 1']
    assert all(c.post_id == 'post_1' and c.owner_id == 'jean.dupont' for c in comments)
    assert len({c.comment_id for c in comments}) == 130          # identifiants uniques
    assert comments[5].author_name == 'Auteur 5' and comments[5].date_text == '3 h'


def test_duplicates_across_passes_are_counted_once(settings):
    """JS_LIRE_COMMS renvoie à chaque passe TOUT ce qui est affiché : pas de doublons attendus."""
    comments = run(FakePostDriver(total=60), settings)
    assert len({(c.author_name, c.text_content) for c in comments}) == len(comments) == 60


def test_respects_max_comments_per_post(settings):
    assert len(run(FakePostDriver(total=500), settings, max_comments_per_post=50)) == 50


def test_stops_by_itself_when_nothing_more_loads(settings):
    driver = FakePostDriver(total=20)
    assert len(run(driver, settings)) == 20
    assert driver.scroll_calls <= 8                  # 3 passes sans nouveauté puis arrêt


def test_pass_limit_bounds_the_loop_and_warns(settings, caplog):
    driver = FakePostDriver(total=100_000)
    with caplog.at_level(logging.WARNING, logger='fb_test_comments'):
        comments = run(driver, settings, max_comment_passes=5, max_comments_per_post=10_000)
    assert driver.scroll_calls == 5 and 0 < len(comments) < 200
    assert any('limite de 5 passes' in message for message in caplog.messages)


def test_expand_buttons_are_clicked_and_their_content_read(settings):
    driver = FakePostDriver(total=80, first=10, expanders=3)
    assert len(run(driver, settings)) == 80


def test_post_that_does_not_open_reads_nothing(settings):
    """Régression v1 : on lisait la page entière et on attribuait au post les commentaires d'autres posts."""
    driver = FakePostDriver(total=50)
    comments = extract_comments(driver, Permalink(driver, opens=False), 'p', 'o',
                                settings.limits, settings.keywords, LOGGER)
    assert comments == [] and driver.read_calls == 0


def test_missing_permalink_returns_empty(settings):
    assert extract_comments(FakePostDriver(5), None, 'p', 'o', settings.limits,
                            settings.keywords, LOGGER) == []


def test_window_is_always_closed_afterwards(settings):
    driver = FakePostDriver(total=30)
    run(driver, settings)
    assert driver.dialog_open is False and driver.closed >= 1


def test_page_navigation_mode_goes_back(settings):
    driver = FakePostDriver(total=20)
    driver.dialog_open = False
    comments = extract_comments(driver, Permalink(driver, opens=False, navigates=True), 'p', 'o',
                                settings.limits, settings.keywords, LOGGER)
    assert len(comments) == 20 and driver.backs == 1


def test_closed_browser_is_raised_but_cleanup_is_attempted(settings):
    driver = FakePostDriver(total=30, read_error=WebDriverException('invalid session id'))
    with pytest.raises(BrowserClosedError):
        run(driver, settings)


def test_non_fatal_error_keeps_what_was_already_read(settings):
    driver = FakePostDriver(total=60)
    original = driver.execute_script
    state = {'n': 0}

    def flaky(code, *args):
        if code is js.JS_LIRE_COMMS:
            state['n'] += 1
            if state['n'] == 3:
                raise WebDriverException('javascript error: element not interactable')
        return original(code, *args)

    driver.execute_script = flaky
    comments = run(driver, settings)
    assert 0 < len(comments) < 60 and driver.dialog_open is False


def test_expand_buttons_are_real_selenium_clicks_limited_per_pass(settings):
    """Les boutons sont cliqués un par un via element.click() (clic fiable), 3 au plus par passe."""
    driver = FakePostDriver(total=80, first=10, expanders=3)
    run(driver, settings)
    assert driver.expand_clicks == 3
    assert driver.expand_args[1] == settings.keywords.expansion_regex and driver.expand_args[2] == 3


def test_post_without_permalink_is_opened_through_its_comment_counter(settings):
    """Sans lien permanent, on clique « N commentaires » au lieu d'abandonner (0 commentaire)."""
    driver = FakePostDriver(total=25)
    original = driver.execute_script
    seen = {}

    def with_counter(code, *args):
        if code is js.JS_BOUTON_COMMENTAIRES:
            seen['regex'] = args[1]
            return Permalink(driver)
        return original(code, *args)

    driver.execute_script = with_counter
    comments = extract_comments(driver, None, 'p', 'o', settings.limits, settings.keywords, LOGGER,
                                article=object())
    assert len(comments) == 25 and seen['regex'] == settings.keywords.comment_count_regex


def test_no_permalink_and_no_counter_reads_nothing(settings):
    driver = FakePostDriver(total=25)
    original = driver.execute_script
    driver.execute_script = lambda code, *a: None if code is js.JS_BOUTON_COMMENTAIRES else original(code, *a)
    assert extract_comments(driver, None, 'p', 'o', settings.limits, settings.keywords, LOGGER,
                            article=object()) == []
    assert driver.read_calls == 0


def test_page_mode_does_not_go_back_twice_when_closing_already_returned(settings):
    """Régression : la fermeture de la visionneuse revient déjà ; un back() de plus remontait
    jusqu'au profil de l'utilisateur."""
    driver = FakePostDriver(total=3)
    original = driver.execute_script

    def closing(code, *args):
        if code is js.JS_FERMER:
            def close():        # fermer la visionneuse = Facebook revient sur le profil
                driver.closed += 1
                driver.current_url = 'https://web.facebook.com/jean/'   # sous-domaine + « / » final
            return [Clicker(close)]
        if code is js.JS_LIRE_COMMS:
            driver.dialog_open = True       # la visionneuse apparaît APRÈS le changement d'URL
        return original(code, *args)

    driver.execute_script = closing
    comments = extract_comments(driver, Permalink(driver, opens=False, navigates=True), 'p', 'o',
                                settings.limits, settings.keywords, LOGGER)
    assert len(comments) == 3 and driver.backs == 0


def test_same_page_ignores_subdomain_slash_and_tracking():
    from ..extractors.posts import _same_page
    assert _same_page('https://www.facebook.com/jean', 'https://web.facebook.com/jean/?__cft__=1')
    assert not _same_page('https://web.facebook.com/photo?fbid=1', 'https://www.facebook.com/jean')
    assert _same_page('https://www.facebook.com/profile.php?id=5', 'https://web.facebook.com/profile.php?id=5&sk=x')
    assert not _same_page('https://www.facebook.com/profile.php?id=5', 'https://www.facebook.com/profile.php?id=6')
