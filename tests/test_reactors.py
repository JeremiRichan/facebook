"""Lecture des personnes ayant réagi : onglets par type, défilement, première réaction gagnante."""

import logging

from fb_modular.browser import js
from fb_modular.extractors.posts import extract_reactions

LOGGER = logging.getLogger('fb_test_reactors')
LABELS = ["Tous, 12", "J'aime 8", "J'adore 4"]


def person(n):
    return [f'https://web.facebook.com/personne.{n}/', f'Personne Numero{n}', '']


class Button:
    def __init__(self, driver):
        self.driver = driver

    def click(self):
        self.driver.dialog_open = True


class Clicker:
    def __init__(self, action):
        self.action = action

    def click(self):
        self.action()


class FakeReactionDriver:
    """Fenêtre des réactions : onglets, listes par type qui se chargent au défilement."""

    def __init__(self, lists, labels=LABELS, paged=5, stale_rows=()):
        self.lists, self.labels, self.paged = lists, labels, paged
        self.stale_rows = list(stale_rows)       # lignes résiduelles de l'ancien onglet
        self.dialog_open, self.tab, self.loaded, self.just_clicked = False, 0, paged, False
        self.current_url = 'https://www.facebook.com/jean'

    def execute_script(self, code, *args):
        if code is js.JS_BOUTON_REACTIONS:
            return Button(self)
        if code is js.JS_DIALOGUES:
            return ['DIALOG'] if self.dialog_open else []
        if code is js.JS_FERMER:
            return [Clicker(lambda: setattr(self, 'dialog_open', False))]
        if code is js.JS_ONGLETS:
            return list(self.labels)
        if code is js.JS_LABELS_REACTIONS:
            return []
        if code is js.JS_CLICK_TAB:
            index = args[1]

            def select():
                self.tab, self.loaded, self.just_clicked = index, self.paged, True
            return Clicker(select)
        if code is js.JS_TAB_SELECTED:
            return True
        if code is js.JS_REACTOR_ROWS:
            rows = self.lists.get(self.tab, [])[:self.loaded]
            if self.just_clicked and self.stale_rows:
                self.just_clicked = False
                return self.stale_rows + rows
            return rows
        if code is js.JS_SCROLL_ZONE:
            self.loaded += self.paged
            return self.loaded
        return True


def go(driver, settings, with_reactors=True, **limits):
    s = settings.with_limits(**limits) if limits else settings
    return extract_reactions(driver, object(), 'post_1', s.keywords, 'jean.dupont', s.limits,
                             with_reactors=with_reactors)


def lists():
    return {1: [person(n) for n in range(0, 8)],          # onglet J'aime : 8 personnes
            2: [person(n) for n in range(100, 104)]}      # onglet J'adore : 4 personnes


def test_reactors_are_read_per_type_with_scrolling(settings):
    result = go(FakeReactionDriver(lists()), settings)
    by_type = {}
    for r in result.reactors:
        by_type.setdefault(r.reaction_type, []).append(r.reactor_id)
    assert len(by_type['like']) == 8 and len(by_type['love']) == 4
    assert by_type['like'][0] == 'personne.0' and by_type['love'][0] == 'personne.100'
    first = result.reactors[0]
    assert (first.post_id, first.owner_id) == ('post_1', 'jean.dupont')
    assert first.reactor_name == 'Personne Numero0'
    assert first.reactor_url == 'https://www.facebook.com/personne.0'


def test_counters_are_still_collected_alongside(settings):
    result = go(FakeReactionDriver(lists()), settings)
    assert result.total == 12 and {r.reaction_type: r.count for r in result.reactions} == {'like': 8, 'love': 4}


def test_not_requested_means_no_reactors_and_no_extra_clicks(settings):
    driver = FakeReactionDriver(lists())
    result = go(driver, settings, with_reactors=False)
    assert result.reactors == [] and result.total == 12 and driver.tab == 0


def test_cap_per_post(settings):
    result = go(FakeReactionDriver(lists()), settings, max_reactors_per_post=6)
    assert len(result.reactors) == 6


def test_a_person_has_one_reaction_stale_rows_are_not_reclassified(settings):
    """Au changement d'onglet, des lignes de l'onglet précédent peuvent rester affichées."""
    stale = [person(0), person(1)]               # déjà lues sous « J'aime »
    result = go(FakeReactionDriver(lists(), stale_rows=stale), settings)
    ids = [r.reactor_id for r in result.reactors]
    assert len(ids) == len(set(ids)) == 12
    assert {r.reaction_type for r in result.reactors if r.reactor_id in ('personne.0', 'personne.1')} == {'like'}


def test_noise_rows_are_ignored(settings):
    junk = {1: [person(1), ['https://web.facebook.com/notifications/', 'Notifications', ''],
                ['https://web.facebook.com/permalink.php?notif_id=1', 'Unread X mentioned you', ''],
                ['https://web.facebook.com/jean/posts/pfbid1', 'Un post', ''],
                ['https://web.facebook.com/personne.2/', '', 'Personne Numero2'],     # nom via aria-label
                ['https://web.facebook.com/personne.3/', '3 mutual friends', '']]}    # pas un nom
    result = go(FakeReactionDriver(junk), settings)
    assert [r.reactor_id for r in result.reactors] == ['personne.1', 'personne.2']


def test_without_typed_tabs_reads_default_list_as_unknown(settings):
    only_all = FakeReactionDriver({0: [person(n) for n in range(3)]}, labels=['Tous, 3'])
    result = go(only_all, settings)
    assert len(result.reactors) == 3 and {r.reaction_type for r in result.reactors} == {'unknown'}


def test_profile_php_reactor_keeps_numeric_id(settings):
    row = {1: [['https://web.facebook.com/profile.php?id=100099&sk=photos', 'Dadan Branham', '']]}
    result = go(FakeReactionDriver(row), settings)
    assert result.reactors[0].reactor_id == '100099'
    assert result.reactors[0].reactor_url == 'https://www.facebook.com/profile.php?id=100099'


def test_window_is_closed_afterwards(settings):
    driver = FakeReactionDriver(lists())
    go(driver, settings)
    assert driver.dialog_open is False
