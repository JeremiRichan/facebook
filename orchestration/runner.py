"""Orchestration complète du scraping : session, liste d'amis, boucle de traitement.

Invariant central : un ami n'est écrit dans les CSV et marqué « traité » QUE si son scraping a
réussi (OK) ou si son profil est réellement indisponible. Une erreur, une coupure réseau ou un
blocage n'écrivent rien : l'ami sera re-tenté au prochain lancement.
"""

from __future__ import annotations

import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from ..browser import js
from ..browser.driver_factory import create_browser, safe_quit
from ..browser.page import (
    detect_block, pause, safe_get,
)
from ..config.settings import ScraperSettings
from ..core.errors import BlockedError, BrowserClosedError, ScraperError
from ..core.logging_setup import configure_logging
from ..core.models import ScrapeResult, Status
from ..core.scoring import compute_fake_score, unavailable_score
from ..core.text_utils import extract_facebook_id, normalise_facebook_url, strip_query
from ..extractors.friends import extract_all_friends
from ..extractors.profiles import scrape_friend_profile
from ..storage.csv_storage import (
    close_all_tables, ensure_pivot_row, open_all_tables, write_scrape_result,
)
from ..storage.maintenance import clean_invalid_data
from ..storage.progress_store import (
    is_already_processed, load_friends_cache, load_processed_ids, save_friends_cache,
    save_progress,
)
from .state_machine import RunState, StateManager

HOME_URL = 'https://www.facebook.com'
ME_URL = 'https://www.facebook.com/me'

EXIT_OK, EXIT_ERROR, EXIT_LOGIN, EXIT_BLOCKED = 0, 1, 2, 3

ScrapeFn = Callable[..., ScrapeResult]


@dataclass
class RunSummary:
    processed: int = 0
    unavailable: int = 0
    failed: int = 0
    verdicts: Counter = field(default_factory=Counter)
    stopped_reason: str = ''
    blocked: bool = False


# -------------------------------------------------------------------------- session

def ensure_logged_in(driver, logger, interactive: bool = True) -> bool:
    """Vérifie la session ; si besoin, laisse l'utilisateur se connecter puis reprend."""
    safe_get(driver, HOME_URL, logger)
    time.sleep(3)
    if detect_block(driver) is None:
        return True
    if not interactive or not sys.stdin.isatty():
        logger.error('Session Facebook absente : connectez-vous une fois en mode interactif.')
        return False
    logger.info('Connectez-vous à Facebook dans la fenêtre Chrome, puis appuyez sur ENTRÉE ici.')
    input()
    safe_get(driver, HOME_URL, logger)
    time.sleep(3)
    return detect_block(driver) is None


def detect_session_identity(driver, logger) -> tuple[Optional[str], str]:
    """Retourne (id de MON profil, URL de MA photo) pour les exclure de la liste d'amis."""
    own_photo = ''
    try:
        own_photo = strip_query(driver.execute_script(js.JS_OWN_PHOTO) or '')
    except Exception:
        pass
    own_id = None
    try:
        safe_get(driver, ME_URL, logger)
        for _ in range(12):                      # /me redirige vers le vrai profil
            time.sleep(0.5)
            current = normalise_facebook_url(driver.current_url)
            if not current.rstrip('/').endswith('/me'):
                break
        own_id = extract_facebook_id(normalise_facebook_url(driver.current_url))
    except ScraperError:
        raise
    except Exception as error:
        logger.debug('identité non détectée : %s', error)
    if own_id:
        logger.info('Votre profil (%s) sera exclu de la liste.', own_id)
    return own_id, own_photo


# --------------------------------------------------------------------- boucle d'amis

def _scrape_with_retries(driver, friend: Dict[str, str], settings: ScraperSettings, logger,
                         own_photo: str, scrape_fn: ScrapeFn) -> ScrapeResult:
    limits = settings.limits
    errors = network_failures = 0
    while True:
        result = scrape_fn(driver, friend, settings, logger, own_photo)
        if result.status in (Status.OK, Status.UNAVAILABLE, Status.BLOCKED,
                             Status.BROWSER_CLOSED):
            return result
        if result.status is Status.NETWORK:
            network_failures += 1
            if network_failures > limits.max_network_retries:
                return result
            wait = min(limits.network_backoff_base * 2 ** (network_failures - 1),
                       limits.network_backoff_max)
            logger.warning('  Réseau instable (%s/%s) : nouvelle tentative dans %.0f s',
                           network_failures, limits.max_network_retries, wait)
            time.sleep(wait)
            continue
        errors += 1                                   # Status.ERROR
        if errors > limits.retries:
            return result
        logger.warning('  Échec (%s) : nouvelle tentative %s/%s', result.error, errors,
                       limits.retries)
        pause(15, 25)


def process_friends(driver, friends: List[dict], tables, settings: ScraperSettings, logger,
                    processed_ids: Set[str], own_photo: str = '',
                    scrape_fn: ScrapeFn = scrape_friend_profile,
                    state: Optional[StateManager] = None) -> RunSummary:
    limits = settings.limits
    summary = RunSummary()
    todo = [f for f in friends if not is_already_processed(f['friend_id'], processed_ids)]
    logger.info('%s amis à traiter (%s déjà faits)', len(todo), len(friends) - len(todo))
    consecutive_failures = 0
    started = time.time()

    try:
        for index, friend in enumerate(todo, 1):
            if limits.friends_per_run and summary.processed >= limits.friends_per_run:
                summary.stopped_reason = f'limite --limit={limits.friends_per_run} atteinte'
                break
            logger.info('[%s/%s] %s (%s)', index, len(todo), friend['display_name'],
                        friend['friend_id'])
            if state:
                state.transition(RunState.PROFILING, friend['friend_id'])

            result = _scrape_with_retries(driver, friend, settings, logger, own_photo, scrape_fn)

            if result.status in (Status.BLOCKED, Status.BROWSER_CLOSED):
                summary.blocked = result.status is Status.BLOCKED
                summary.stopped_reason = f'{result.status.value} : {result.error}'
                logger.error('ARRÊT : %s. Résolvez-le dans Chrome puis relancez la commande : '
                             'la reprise est automatique.', summary.stopped_reason)
                break

            if not result.writable:
                summary.failed += 1
                consecutive_failures += 1
                logger.error('  Ami NON enregistré (%s) — il sera re-tenté au prochain lancement '
                             '[%s/%s échecs consécutifs]', result.error, consecutive_failures,
                             limits.max_consecutive_failures)
                if consecutive_failures >= limits.max_consecutive_failures:
                    summary.stopped_reason = 'trop d\'échecs consécutifs'
                    logger.error('ARRÊT : %s (Facebook limite peut-être le compte, ou le réseau '
                                 'est coupé).', summary.stopped_reason)
                    break
                pause(limits.pause_min, limits.pause_max)
                continue
            consecutive_failures = 0

            if result.status is Status.UNAVAILABLE:
                score = unavailable_score()
                summary.unavailable += 1
            else:
                score = compute_fake_score(result.profile)
            write_scrape_result(tables, result, score)
            save_progress(settings.paths.progress_csv, friend['friend_id'])
            processed_ids.add(friend['friend_id'])
            summary.processed += 1
            summary.verdicts[score.verdict] += 1

            elapsed = time.time() - started
            remaining = len(todo) - index
            logger.info('  => %s %s | %s posts | ~%.1f min/ami, reste ~%.1f h',
                        score.score_fake, score.verdict, result.profile.post_count,
                        elapsed / summary.processed / 60,
                        remaining * elapsed / summary.processed / 3600)

            if summary.processed % limits.batch_size == 0:
                logger.info('Pause de %.0f s...', limits.batch_pause)
                time.sleep(limits.batch_pause + _jitter(10))
            else:
                pause(limits.pause_min, limits.pause_max)
    except KeyboardInterrupt:
        summary.stopped_reason = 'interruption utilisateur'
        logger.info('Interruption : les données déjà écrites sont conservées.')
    return summary


def _jitter(maximum: float) -> float:
    return random.uniform(0, maximum)


# ------------------------------------------------------------------------ point d'entrée

def run_scraper(settings: ScraperSettings, headless: Optional[bool] = None,
                interactive: bool = True) -> int:
    if headless is not None:
        settings = settings.with_features(headless=headless)
    features, paths = settings.features, settings.paths
    logger = configure_logging(paths.log_file, 10 if features.verbose else 20)
    state = StateManager(logger)
    logger.info('FACEBOOK SCRAPER MODULAIRE v2')

    if features.retry_zero_posts:
        report = clean_invalid_data(paths, retry_zero_posts=True)
        for line in report.summary_lines():
            logger.info('Reprise : %s', line)

    try:
        driver = create_browser(paths.profile_dir, features.headless, features.no_sandbox,
                                features.chrome_version)
    except Exception as error:
        logger.error('Impossible d\'initialiser le navigateur : %s', error)
        return EXIT_ERROR
    state.transition(RunState.BROWSER_READY)

    tables = open_all_tables({
        'users': paths.users_csv, 'relations': paths.relations_csv, 'posts': paths.posts_csv,
        'comments': paths.comments_csv, 'photos': paths.photos_csv,
        'reactions': paths.reactions_csv, 'reactors': paths.reactors_csv,
    })
    exit_code = EXIT_OK
    try:
        if not ensure_logged_in(driver, logger, interactive):
            logger.error('Connexion Facebook impossible.')
            return EXIT_LOGIN

        ensure_pivot_row(tables, datetime.now().isoformat())
        processed_ids = load_processed_ids(paths.progress_csv, paths.users_csv)
        logger.info('Reprise : %s IDs déjà traités', len(processed_ids))
        own_id, own_photo = detect_session_identity(driver, logger)

        friends = None
        if not features.refresh_friends:
            friends = load_friends_cache(paths.friends_cache, settings.limits.friends_cache_hours)
            if friends:
                friends = [f for f in friends if f['friend_id'] != own_id]
                logger.info('%s amis chargés depuis le cache (--refresh-friends pour rescanner)',
                            len(friends))
        if not friends:
            friends = extract_all_friends(driver, settings, logger, {own_id} if own_id else set())
            if friends:
                save_friends_cache(paths.friends_cache, friends)
        if not friends:
            logger.error('Aucun ami trouvé.')
            state.transition(RunState.FAILED, 'aucun ami')
            return EXIT_ERROR
        state.transition(RunState.FRIENDS_EXTRACTED)

        summary = process_friends(driver, friends, tables, settings, logger, processed_ids,
                                  own_photo, scrape_fn=scrape_friend_profile, state=state)
        if summary.blocked:
            state.transition(RunState.BLOCKED, summary.stopped_reason)
            exit_code = EXIT_BLOCKED
        elif summary.stopped_reason.startswith(('interruption', 'limite')):
            state.transition(RunState.PAUSED, summary.stopped_reason)
        elif summary.stopped_reason:
            state.transition(RunState.FAILED, summary.stopped_reason)
            exit_code = EXIT_ERROR
        else:
            state.transition(RunState.COMPLETED)
        logger.info('Terminé : %s traités (%s indisponibles), %s échecs — verdicts : %s%s',
                    summary.processed, summary.unavailable, summary.failed,
                    dict(summary.verdicts) or '-',
                    f' — arrêt : {summary.stopped_reason}' if summary.stopped_reason else '')
    except BlockedError as error:
        logger.error('ARRÊT : %s', error)
        exit_code = EXIT_BLOCKED
    except BrowserClosedError as error:
        logger.error('Navigateur fermé : %s', error)
        exit_code = EXIT_ERROR
    except ScraperError as error:
        logger.error('Erreur : %s', error)
        exit_code = EXIT_ERROR
    except KeyboardInterrupt:
        logger.info('Interruption utilisateur — données sauvegardées')
    except Exception as error:
        import traceback
        logger.error('Erreur inattendue : %s\n%s', error, traceback.format_exc())
        exit_code = EXIT_ERROR
    finally:
        close_all_tables(tables)
        safe_quit(driver)
    return exit_code
