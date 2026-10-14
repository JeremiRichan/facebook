import csv
from pathlib import Path


from fb_modular.core.models import PostData, ProfileData, ScrapeResult, Status
from fb_modular.orchestration.runner import process_friends
from fb_modular.storage.csv_storage import close_all_tables, open_all_tables
from fb_modular.storage.progress_store import load_processed_ids


def friends(*ids):
    return [{'friend_id': i, 'display_name': f'Name {i}', 'profile_url': f'https://www.facebook.com/{i}',
             'photo_url': ''} for i in ids]


def open_tables(settings):
    p = settings.paths
    return open_all_tables({
        'users': p.users_csv, 'relations': p.relations_csv, 'posts': p.posts_csv,
        'comments': p.comments_csv, 'photos': p.photos_csv, 'reactions': p.reactions_csv})


def make_result(friend, status=Status.OK, posts=2, error=''):
    profile = ProfileData(friend['friend_id'], friend['display_name'], friend['profile_url'],
                          photo_url='http://p', bio='bio', post_count=posts, comment_count=1,
                          reaction_count=3)
    result = ScrapeResult(profile=profile, status=status, error=error)
    for n in range(posts):
        result.posts.append(PostData(f'post_{friend["friend_id"]}_{n}', friend['friend_id'], 'texte'))
    return result


class Script:
    """Faux scraper : renvoie les statuts programmés pour chaque ami, dans l'ordre."""

    def __init__(self, plan):
        self.plan, self.calls = {k: list(v) for k, v in plan.items()}, []

    def __call__(self, driver, friend, settings, logger, own_photo=''):
        fid = friend['friend_id']
        self.calls.append(fid)
        step = self.plan.get(fid, [Status.OK])
        status = step.pop(0) if len(step) > 1 else step[0]
        return make_result(friend, status, posts=2 if status is Status.OK else 0,
                           error='' if status is Status.OK else f'{status.value} simulé')


def read_ids(path: Path):
    with open(path, newline='', encoding='utf-8') as handle:
        rows = list(csv.reader(handle))
    return [r[0] for r in rows[1:]]


def run(settings, logger, plan, ids, processed=None, **limits):
    settings = settings.with_limits(**limits) if limits else settings
    tables = open_tables(settings)
    script = Script(plan)
    summary = process_friends(None, friends(*ids), tables, settings, logger,
                              set() if processed is None else processed, scrape_fn=script)
    close_all_tables(tables)
    return summary, script


def test_success_writes_everything_and_marks_progress(settings, logger):
    summary, _ = run(settings, logger, {}, ['a.b', 'c.d'])
    assert summary.processed == 2
    assert read_ids(settings.paths.users_csv) == ['a.b', 'c.d']
    assert read_ids(settings.paths.progress_csv) == ['a.b', 'c.d']
    assert len(read_ids(settings.paths.posts_csv)) == 4
    assert read_ids(settings.paths.relations_csv) == ['__moi__', '__moi__']


def test_error_is_never_written_as_a_processed_friend(settings, logger):
    """Régression : la v1 enregistrait un échec comme « 0 post, SUSPECT » et le marquait traité."""
    summary, script = run(settings, logger, {'a.b': [Status.ERROR]}, ['a.b', 'c.d'])
    assert summary.failed == 1 and summary.processed == 1
    assert read_ids(settings.paths.users_csv) == ['c.d']
    assert read_ids(settings.paths.progress_csv) == ['c.d']
    assert script.calls.count('a.b') == 2            # 1 essai + 1 nouvelle tentative (retries=1)


def test_failed_friend_is_retried_on_next_run(settings, logger):
    run(settings, logger, {'a.b': [Status.ERROR]}, ['a.b'])
    processed = load_processed_ids(settings.paths.progress_csv, settings.paths.users_csv)
    assert 'a.b' not in processed
    summary, _ = run(settings, logger, {}, ['a.b'], processed=processed)
    assert summary.processed == 1 and read_ids(settings.paths.users_csv) == ['a.b']


def test_blocked_stops_immediately_and_writes_nothing(settings, logger):
    summary, script = run(settings, logger, {'a.b': [Status.BLOCKED]}, ['a.b', 'c.d', 'e.f'])
    assert summary.blocked and script.calls == ['a.b']
    assert not settings.paths.progress_csv.exists()


def test_browser_closed_stops(settings, logger):
    summary, script = run(settings, logger, {'a.b': [Status.BROWSER_CLOSED]}, ['a.b', 'c.d'])
    assert summary.stopped_reason.startswith('browser_closed') and script.calls == ['a.b']


def test_consecutive_failures_stop_the_run(settings, logger):
    plan = {i: [Status.ERROR] for i in ('a.a', 'b.b', 'c.c', 'd.d', 'e.e')}
    summary, script = run(settings, logger, plan, list(plan), retries=0, max_consecutive_failures=3)
    assert summary.failed == 3 and 'consécutifs' in summary.stopped_reason
    assert script.calls == ['a.a', 'b.b', 'c.c']


def test_a_success_resets_the_failure_counter(settings, logger):
    plan = {'a.a': [Status.ERROR], 'b.b': [Status.ERROR], 'c.c': [Status.OK],
            'd.d': [Status.ERROR], 'e.e': [Status.ERROR], 'f.f': [Status.OK]}
    summary, _ = run(settings, logger, plan, list(plan), retries=0, max_consecutive_failures=3)
    assert summary.processed == 2 and summary.failed == 4 and not summary.stopped_reason


def test_network_errors_back_off_then_succeed(settings, logger):
    plan = {'a.b': [Status.NETWORK, Status.NETWORK, Status.OK]}
    summary, script = run(settings, logger, plan, ['a.b'])
    assert summary.processed == 1 and script.calls == ['a.b'] * 3


def test_network_errors_give_up_after_max_retries(settings, logger):
    summary, script = run(settings, logger, {'a.b': [Status.NETWORK]}, ['a.b'],
                          max_network_retries=2, max_consecutive_failures=1)
    assert summary.failed == 1 and script.calls == ['a.b'] * 3
    assert not settings.paths.users_csv.exists() or read_ids(settings.paths.users_csv) == []


def test_unavailable_profile_is_recorded_once_with_its_verdict(settings, logger):
    summary, _ = run(settings, logger, {'a.b': [Status.UNAVAILABLE]}, ['a.b'])
    assert summary.unavailable == 1 and summary.verdicts['INDISPONIBLE'] == 1
    with open(settings.paths.users_csv, newline='', encoding='utf-8') as handle:
        rows = list(csv.reader(handle))
    assert rows[1][6] == 'INDISPONIBLE'


def test_already_processed_friends_are_skipped(settings, logger):
    summary, script = run(settings, logger, {}, ['a.b', 'c.d'], processed={'a.b'})
    assert script.calls == ['c.d'] and summary.processed == 1


def test_limit_counts_processed_friends_not_scanned_ones(settings, logger):
    """Régression : --max-friends limitait l'EXTRACTION, donc rien de neuf à la reprise."""
    summary, script = run(settings, logger, {}, ['a.a', 'b.b', 'c.c', 'd.d'],
                          processed={'a.a', 'b.b'}, friends_per_run=1)
    assert script.calls == ['c.c'] and summary.processed == 1
    assert 'limite' in summary.stopped_reason
