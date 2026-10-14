import csv

from fb_modular.cli import build_parser, settings_from_args
from fb_modular.core.models import PostData, ProfileData, ReactorData, ScrapeResult
from fb_modular.core.scoring import compute_fake_score
from fb_modular.storage.csv_storage import CSV_HEADERS, close_all_tables, open_all_tables, write_scrape_result
from fb_modular.storage.maintenance import clean_invalid_data
from .test_maintenance import build_dataset, read, write


def tables_for(settings):
    p = settings.paths
    return open_all_tables({'users': p.users_csv, 'relations': p.relations_csv, 'posts': p.posts_csv,
                            'comments': p.comments_csv, 'photos': p.photos_csv,
                            'reactions': p.reactions_csv, 'reactors': p.reactors_csv})


def test_reactors_are_written_with_the_documented_columns(settings):
    profile = ProfileData('jean.dupont', 'Jean', 'u', photo_url='p', bio='b', post_count=1)
    result = ScrapeResult(profile=profile)
    result.posts.append(PostData('post_1', 'jean.dupont', 'texte'))
    result.reactors += [ReactorData('post_1', 'jean.dupont', 'samia.rakoto', 'Samia Rakoto',
                                    'https://www.facebook.com/samia.rakoto', 'like'),
                        ReactorData('post_1', 'jean.dupont', '100099', 'Dadan', 'https://www.facebook.com/profile.php?id=100099', 'love')]
    tables = tables_for(settings)
    write_scrape_result(tables, result, compute_fake_score(profile))
    close_all_tables(tables)
    with open(settings.paths.reactors_csv, newline='', encoding='utf-8') as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ['id_post', 'id_reacteur', 'nom_reacteur', 'url_reacteur', 'type', 'extraction_date']
    assert [r[:2] + [r[4]] for r in rows[1:]] == [['post_1', 'samia.rakoto', 'like'], ['post_1', '100099', 'love']]


def test_write_works_without_the_reactors_table(settings):
    """Compatibilité : un appelant qui n'ouvre pas la table (ancien code) ne casse pas."""
    p = settings.paths
    tables = open_all_tables({'users': p.users_csv, 'relations': p.relations_csv, 'posts': p.posts_csv,
                              'comments': p.comments_csv, 'photos': p.photos_csv, 'reactions': p.reactions_csv})
    profile = ProfileData('a.b', 'A', 'u', photo_url='p', bio='b')
    write_scrape_result(tables, ScrapeResult(profile=profile), compute_fake_score(profile))
    close_all_tables(tables)
    assert read(p.users_csv)[0][0] == 'a.b'


def test_clean_removes_reactor_rows_of_purged_posts(settings):
    p = settings.paths
    build_dataset(p)
    write(p.reactors_csv, CSV_HEADERS['reactors'], [
        ['p1', 'samia.rakoto', 'Samia', 'u', 'like', 'now'],
        ['p2', 'tiers.x', 'Tiers', 'u', 'like', 'now']])          # p2 = post de « permalink.php »
    clean_invalid_data(p)
    assert [r[0] for r in read(p.reactors_csv)] == ['p1']


def test_cli_reactors_flag(tmp_path):
    base = ['--base-dir', str(tmp_path)]
    s = settings_from_args(build_parser().parse_args(base))
    assert s.features.reactors is True                               # noms des réacteurs : actif par défaut
    s = settings_from_args(build_parser().parse_args(base + ['--no-reactors']))
    assert s.features.reactors is False
    s = settings_from_args(build_parser().parse_args(base + ['--reactors', '--max-reactors', '50']))
    assert s.features.reactors and s.limits.max_reactors_per_post == 50
    s = settings_from_args(build_parser().parse_args(base + ['--reactors', '--no-reactions']))
    assert s.features.reactors is False                              # sans réactions, pas de noms
