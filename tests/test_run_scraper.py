import csv

import pytest

from fb_modular.core.models import PostData, ProfileData, ScrapeResult, Status
from fb_modular.orchestration import runner


class DummyDriver:
    quit_called = False

    def quit(self):
        DummyDriver.quit_called = True


def fr(*ids):
    return [{'friend_id': i, 'display_name': f'N {i}', 'profile_url': f'https://www.facebook.com/{i}',
             'photo_url': ''} for i in ids]


@pytest.fixture
def env(monkeypatch, settings):
    state = {'extract_calls': 0, 'scraped': [], 'statuses': {}}
    monkeypatch.setattr(runner, 'create_browser', lambda *a, **k: DummyDriver())
    monkeypatch.setattr(runner, 'ensure_logged_in', lambda *a, **k: True)
    monkeypatch.setattr(runner, 'detect_session_identity', lambda d, l: ('moi.meme', 'https://scontent.x/own.jpg'))

    def fake_extract(driver, s, logger, exclude=None):
        state['extract_calls'] += 1
        assert 'moi.meme' in exclude          # mon profil est exclu de l'extraction
        return fr('a.a', 'b.b', 'c.c')

    def fake_scrape(driver, friend, s, logger, own_photo=''):
        state['scraped'].append(friend['friend_id'])
        status = state['statuses'].get(friend['friend_id'], Status.OK)
        profile = ProfileData(friend['friend_id'], friend['display_name'], friend['profile_url'],
                              photo_url='p', bio='b', post_count=1, comment_count=1, reaction_count=1)
        result = ScrapeResult(profile=profile, status=status, error='' if status is Status.OK else 'x')
        result.posts.append(PostData('post_' + friend['friend_id'], friend['friend_id'], 't'))
        return result

    monkeypatch.setattr(runner, 'extract_all_friends', fake_extract)
    monkeypatch.setattr(runner, 'scrape_friend_profile', fake_scrape)
    DummyDriver.quit_called = False
    return state


def rows(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.reader(handle))[1:]


def test_full_run_then_resume_uses_cache_and_skips_done(env, settings):
    assert runner.run_scraper(settings) == runner.EXIT_OK
    assert [r[0] for r in rows(settings.paths.users_csv)] == ['__moi__', 'a.a', 'b.b', 'c.c']
    assert settings.paths.friends_cache.exists() and DummyDriver.quit_called
    env['scraped'].clear()
    assert runner.run_scraper(settings) == runner.EXIT_OK
    assert env['extract_calls'] == 1               # 2e lancement : liste lue dans le cache
    assert env['scraped'] == []                    # et rien à refaire
    assert len(rows(settings.paths.users_csv)) == 4   # pas de doublon (pivot compris)


def test_refresh_friends_ignores_cache(env, settings):
    runner.run_scraper(settings)
    runner.run_scraper(settings.with_features(refresh_friends=True))
    assert env['extract_calls'] == 2


def test_blocked_returns_exit_3_and_keeps_earlier_work(env, settings):
    env['statuses']['b.b'] = Status.BLOCKED
    assert runner.run_scraper(settings) == runner.EXIT_BLOCKED
    assert [r[0] for r in rows(settings.paths.users_csv)] == ['__moi__', 'a.a']
    assert env['scraped'] == ['a.a', 'b.b']        # c.c jamais tenté après le blocage
    assert DummyDriver.quit_called                 # le navigateur est fermé même en cas d'arrêt
    env['statuses'].clear()
    assert runner.run_scraper(settings) == runner.EXIT_OK
    assert [r[0] for r in rows(settings.paths.users_csv)] == ['__moi__', 'a.a', 'b.b', 'c.c']


def test_limit_pauses_the_run(env, settings):
    assert runner.run_scraper(settings.with_limits(friends_per_run=2)) == runner.EXIT_OK
    assert env['scraped'] == ['a.a', 'b.b']


def test_login_failure_returns_exit_2(env, settings, monkeypatch):
    monkeypatch.setattr(runner, 'ensure_logged_in', lambda *a, **k: False)
    assert runner.run_scraper(settings) == runner.EXIT_LOGIN and DummyDriver.quit_called


def test_no_friends_found_returns_error(env, settings, monkeypatch):
    monkeypatch.setattr(runner, 'extract_all_friends', lambda *a, **k: [])
    assert runner.run_scraper(settings) == runner.EXIT_ERROR
    assert not settings.paths.friends_cache.exists()


def test_retry_zero_posts_purges_then_rescrapes(env, settings):
    runner.run_scraper(settings)
    users = settings.paths.users_csv
    text = users.read_text(encoding='utf-8').replace('peu_posts', 'zero_post')   # simule d'anciens échecs
    users.write_text(text, encoding='utf-8')
    env['scraped'].clear()
    runner.run_scraper(settings.with_features(retry_zero_posts=True))
    assert sorted(env['scraped']) == ['a.a', 'b.b', 'c.c']
    ids = [r[0] for r in rows(users)]
    assert sorted(ids) == ['__moi__', 'a.a', 'b.b', 'c.c']        # pas de doublons après reprise
