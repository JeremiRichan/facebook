import csv

from fb_modular.cli import build_parser, settings_from_args
from fb_modular.storage.csv_storage import CSV_HEADERS
from fb_modular.storage.maintenance import clean_invalid_data


def write(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def read(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.reader(handle))[1:]


def build_dataset(paths):
    now = '2026-10-13T14:00:00'
    write(paths.users_csv, CSV_HEADERS['users'], [
        ['__moi__', 'Moi', 'Inconnue', '', '', 0.0, 'REEL', 'compte_pivot', now],
        ['samia.rakoto', 'Samia', 'Inconnue', 'bio', 'p', 0.1, 'REEL', 'aucun', now],
        ['permalink.php', 'Unread Raïssa mentioned you', 'Inconnue', '', '', 0.55, 'SUSPECT', 'zero_post', now],
        ['onthisday', 'You have memories', 'Inconnue', '', '', 0.55, 'SUSPECT', 'zero_post', now],
        ['vide.vide', 'Vide', 'Inconnue', '', '', 0.55, 'SUSPECT', 'pas_photo | zero_post', now],
    ])
    write(paths.posts_csv, CSV_HEADERS['posts'], [
        ['p1', 'samia.rakoto', 'texte', '', 1, 1, '[]', now],
        ['p2', 'permalink.php', 'junk\nmultiligne', '', 0, 0, '[]', now],
    ])
    write(paths.comments_csv, CSV_HEADERS['comments'], [
        ['c1', 'p1', 'samia.rakoto', 'ok', 'X', '', now],
        ['c2', 'p2', 'permalink.php', 'junk', 'X', '', now],
    ])
    write(paths.reactions_csv, CSV_HEADERS['reactions'], [
        ['r1', 'p1', 'like', 3, now], ['r2', 'p2', 'like', 1, now]])
    write(paths.photos_csv, CSV_HEADERS['photos'], [
        ['ph1', 'samia.rakoto', 'u', 'PROFIL', now], ['ph2', 'onthisday', 'u', 'PROFIL', now]])
    write(paths.relations_csv, CSV_HEADERS['relations'], [
        ['__moi__', 'samia.rakoto', 'MON_AMI', now], ['__moi__', 'permalink.php', 'MON_AMI', now],
        ['__moi__', 'onthisday', 'MON_AMI', now]])
    write(paths.progress_csv, ['id_traite'], [['samia.rakoto'], ['permalink.php'], ['onthisday']])


def test_clean_removes_fake_friends_everywhere_and_keeps_real_data(settings):
    p = settings.paths
    build_dataset(p)
    report = clean_invalid_data(p)
    assert report.bad_ids == {'permalink.php', 'onthisday'}
    assert [r[0] for r in read(p.users_csv)] == ['__moi__', 'samia.rakoto', 'vide.vide']
    assert [r[0] for r in read(p.posts_csv)] == ['p1']
    assert [r[0] for r in read(p.comments_csv)] == ['c1']
    assert [r[0] for r in read(p.reactions_csv)] == ['r1']
    assert [r[0] for r in read(p.photos_csv)] == ['ph1']
    assert [r[1] for r in read(p.relations_csv)] == ['samia.rakoto']
    assert [r[0] for r in read(p.progress_csv)] == ['samia.rakoto']
    assert report.backups, 'des sauvegardes .bak-<date> doivent exister'


def test_dry_run_changes_nothing(settings):
    p = settings.paths
    build_dataset(p)
    before = p.users_csv.read_text(encoding='utf-8')
    report = clean_invalid_data(p, dry_run=True)
    assert report.removed['Facebook_User.csv'] == 2
    assert p.users_csv.read_text(encoding='utf-8') == before and not report.backups


def test_retry_zero_posts_also_removes_failed_looking_profiles(settings):
    p = settings.paths
    build_dataset(p)
    report = clean_invalid_data(p, retry_zero_posts=True)
    assert 'vide.vide' in report.bad_ids and 'samia.rakoto' not in report.bad_ids
    assert [r[0] for r in read(p.users_csv)] == ['__moi__', 'samia.rakoto']


def test_clean_is_idempotent(settings):
    p = settings.paths
    build_dataset(p)
    clean_invalid_data(p)
    again = clean_invalid_data(p)
    assert not again.bad_ids and not any(again.removed.values())


def test_clean_on_missing_files_is_harmless(settings):
    report = clean_invalid_data(settings.paths)
    assert report.bad_ids == set()


def test_cli_limit_and_alias_map_to_friends_per_run(tmp_path):
    for flag in ('--limit', '--max-friends'):
        args = build_parser().parse_args(['--base-dir', str(tmp_path), flag, '5'])
        s = settings_from_args(args)
        assert s.limits.friends_per_run == 5
        assert s.limits.max_friends_total == 2600     # l'extraction n'est plus tronquée


def test_cli_flags(tmp_path):
    args = build_parser().parse_args(['--base-dir', str(tmp_path), '--no-comments',
                                      '--no-reactions', '--pause-min', '1', '--pause-max', '2',
                                      '--chrome-version', '155'])
    s = settings_from_args(args)
    assert not s.features.comments and not s.features.reactions
    assert (s.limits.pause_min, s.limits.pause_max) == (1.0, 2.0)
    assert s.features.chrome_version == 155
    assert build_parser().parse_args([]).command == 'run'
