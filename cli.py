"""Point d'entrée CLI du scraper modulaire.

    python -m fb_modular [run] [options]     lance le scraping (reprise automatique)
    python -m fb_modular clean [--dry-run]   purge les faux amis / échecs des CSV
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .config.settings import ScraperSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='fb_modular', description='Scraper Facebook modulaire (usage pédagogique)')
    parser.add_argument('command', nargs='?', choices=['run', 'clean'], default='run',
                        help='run (défaut) : scraper ; clean : nettoyer les CSV')
    parser.add_argument('--base-dir', type=Path, default=None,
                        help='dossier des CSV et du profil Chrome (défaut : dossier parent du paquet)')
    parser.add_argument('--verbose', action='store_true', help='logs détaillés (DEBUG)')

    volume = parser.add_argument_group('volume')
    volume.add_argument('--limit', '--max-friends', dest='limit', type=int, default=None,
                        help='nombre d\'amis à TRAITER sur ce lancement (0 = tous). '
                             '--max-friends est conservé comme alias.')
    volume.add_argument('--max-scan', type=int, default=None,
                        help='nombre max d\'amis à extraire de la liste (défaut 2600)')
    volume.add_argument('--max-posts', type=int, default=None, help='posts max par ami (défaut 20)')
    volume.add_argument('--max-comments', type=int, default=None,
                        help='commentaires max par post (défaut 300)')
    volume.add_argument('--reactors', action='store_true',
                        help='lire les noms de ceux qui ont réagi (Facebook_Reactor.csv) : '
                             'ACTIVÉ par défaut (option conservée pour compatibilité)')
    volume.add_argument('--no-reactors', action='store_true',
                        help='ne pas lire les noms de ceux qui ont réagi (plus rapide, moins exposé)')
    volume.add_argument('--max-reactors', type=int, default=None,
                        help='personnes lues par post avec --reactors (défaut 200)')
    volume.add_argument('--no-comments', action='store_true', help='mode rapide : sans commentaires')
    volume.add_argument('--no-reactions', action='store_true', help='mode rapide : sans réactions')

    rhythm = parser.add_argument_group('rythme et robustesse')
    rhythm.add_argument('--pause-min', type=float, default=None, help='pause min entre amis (s)')
    rhythm.add_argument('--pause-max', type=float, default=None, help='pause max entre amis (s)')
    rhythm.add_argument('--batch-size', type=int, default=None, help='amis avant la longue pause')
    rhythm.add_argument('--batch-pause', type=float, default=None, help='durée de la longue pause (s)')
    rhythm.add_argument('--retries', type=int, default=None, help='nouvelles tentatives sur erreur')
    rhythm.add_argument('--max-failures', type=int, default=None,
                        help='échecs consécutifs avant arrêt (défaut 3)')

    session = parser.add_argument_group('session et reprise')
    session.add_argument('--headless', action='store_true', help='Chrome sans fenêtre')
    session.add_argument('--chrome-version', type=int, default=None,
                         help='forcer la version de Chrome (défaut : détection automatique)')
    session.add_argument('--no-sandbox', action='store_true',
                         help='uniquement si Chrome tourne en root')
    session.add_argument('--refresh-friends', action='store_true',
                         help='ignorer le cache et rescanner la liste d\'amis')
    session.add_argument('--retry-zero-posts', action='store_true',
                         help='re-scraper les amis enregistrés à 0 post (sauvegarde .bak)')

    clean = parser.add_argument_group('clean')
    clean.add_argument('--dry-run', action='store_true', help='clean : afficher sans modifier')
    return parser


def settings_from_args(args: argparse.Namespace) -> ScraperSettings:
    settings = ScraperSettings.from_base_dir(args.base_dir)
    limit_map = {
        'friends_per_run': args.limit, 'max_friends_total': args.max_scan,
        'max_posts_per_friend': args.max_posts, 'max_comments_per_post': args.max_comments,
        'max_reactors_per_post': args.max_reactors,
        'pause_min': args.pause_min, 'pause_max': args.pause_max, 'batch_size': args.batch_size,
        'batch_pause': args.batch_pause, 'retries': args.retries,
        'max_consecutive_failures': args.max_failures,
    }
    settings = settings.with_limits(**{k: v for k, v in limit_map.items() if v is not None})
    return settings.with_features(
        comments=not args.no_comments, reactions=not args.no_reactions,
        reactors=not args.no_reactors and not args.no_reactions, headless=args.headless,
        no_sandbox=args.no_sandbox, chrome_version=args.chrome_version,
        refresh_friends=args.refresh_friends, retry_zero_posts=args.retry_zero_posts,
        verbose=args.verbose)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_args(args)
    if settings.limits.pause_min > settings.limits.pause_max:
        raise SystemExit('--pause-min doit être <= --pause-max')

    if args.command == 'clean':
        from .storage.maintenance import clean_invalid_data
        report = clean_invalid_data(settings.paths, retry_zero_posts=args.retry_zero_posts,
                                    dry_run=args.dry_run)
        print('(simulation, rien n\'est modifié)' if args.dry_run else 'Nettoyage effectué :')
        print('\n'.join(report.summary_lines()))
        if report.bad_ids:
            print('Exemples d\'identifiants retirés :', ', '.join(sorted(report.bad_ids)[:10]))
        return 0

    from .orchestration.runner import run_scraper   # import tardif : Selenium seulement si besoin
    return run_scraper(settings)


if __name__ == '__main__':
    raise SystemExit(main())
