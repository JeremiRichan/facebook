"""Scraping d'un profil d'ami : infos, puis publications (réactions + commentaires)."""

from __future__ import annotations

import json
import random
import time
import traceback
from pathlib import Path
from typing import Dict

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from ..browser import js
from ..browser.page import (
    close_overlays, raise_if_blocked, safe_get, scroll_window_and_wait, wait_for_main,
)
from ..config.settings import ScraperSettings
from ..core.errors import (
    BlockedError, BrowserClosedError, NetworkError, ScraperError, classify_exception,
)
from ..core.models import PostData, ProfileData, ScrapeResult, Status
from ..core.text_utils import strip_query
from .posts import extract_comments, extract_reactions, generate_id


def scrape_friend_profile(driver, friend: Dict[str, str], settings: ScraperSettings, logger,
                          own_photo: str = '') -> ScrapeResult:
    """Scrape un ami et retourne un ScrapeResult. Ne lève jamais d'exception.

    Le `status` indique ce qu'il faut faire ensuite : OK/UNAVAILABLE -> écrire ; ERROR/NETWORK
    -> ne rien écrire et réessayer ; BLOCKED/BROWSER_CLOSED -> arrêter le programme.
    """
    profile = ProfileData(
        friend_id=friend['friend_id'], display_name=friend['display_name'],
        profile_url=friend['profile_url'], photo_url=friend.get('photo_url', ''),
        comments_collected=settings.features.comments,
        reactions_collected=settings.features.reactions,
    )
    result = ScrapeResult(profile=profile)
    try:
        _scrape(driver, friend, settings, logger, own_photo, result)
    except Exception as error:   # on traduit TOUT en statut : le runner décide de la suite
        translated = classify_exception(error)
        if isinstance(translated, BlockedError):
            result.status = Status.BLOCKED
        elif isinstance(translated, BrowserClosedError):
            result.status = Status.BROWSER_CLOSED
        elif isinstance(translated, NetworkError):
            result.status = Status.NETWORK
        else:
            result.status = Status.ERROR
            logger.error('  Erreur profil : %s\n%s', error, traceback.format_exc())
        message = str(translated or error)
        result.error = (message.splitlines() or [type(error).__name__])[0]
        if result.status is not Status.ERROR:
            logger.warning('  %s : %s', result.status.value, result.error)
    profile.error_message = result.error or None
    return result


def _scrape(driver, friend, settings: ScraperSettings, logger, own_photo: str,
            result: ScrapeResult) -> None:
    kw, limits = settings.keywords, settings.limits
    profile = result.profile

    logger.info('  Chargement : %s', friend['profile_url'])
    safe_get(driver, friend['profile_url'], logger)
    wait_for_main(driver, 20)
    time.sleep(random.uniform(1.5, 2.5))
    raise_if_blocked(driver)
    close_overlays(driver)

    for _ in range(12):      # le fil se rend après le cadre : on lui laisse jusqu'à ~6 s
        if driver.execute_script(
                'return document.querySelectorAll(\'div[role="article"]\').length;'):
            break
        time.sleep(0.5)

    infos = driver.execute_script(js.JS_PROFILE_INFOS, kw.bio_regex, kw.joined_regex,
                                  kw.unavailable_regex, strip_query(own_photo)) or {}
    articles_present = driver.execute_script(
        'return document.querySelectorAll(\'div[role="article"]\').length;')
    if infos.get('gone') and not articles_present:
        result.status = Status.UNAVAILABLE
        logger.info('  Profil indisponible (supprimé / restreint)')
        return

    profile.bio = infos.get('bio', '')
    if infos.get('date'):
        profile.account_created = infos['date']
    photo = infos.get('photo') or profile.photo_url
    profile.photo_url = '' if (own_photo and strip_query(photo) == strip_query(own_photo)) else photo
    logger.info('  Bio : %s | création : %s', profile.bio[:80] or '(vide)', profile.account_created)

    seen_keys: set = set()
    stalls = end_of_page = scrolls = 0
    while (stalls < limits.profile_stall_limit and end_of_page < 3
           and scrolls < limits.max_scrolls_profile
           and profile.post_count < limits.max_posts_per_friend):
        scrolls += 1
        articles = driver.execute_script(js.JS_POSTS, kw.comment_prefixes, friend['friend_id']) or []
        logger.info('  scroll %s : %s post(s) détecté(s) par le JS, %s déjà vus', scrolls,
                    len(articles), len(seen_keys))
        fresh = 0
        for article, key, text, date, link in articles:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            fresh += 1
            try:
                _process_post(driver, settings, logger, result, article, text, date, link)
            except StaleElementReferenceException:
                seen_keys.discard(key)        # le DOM a changé : on retentera au prochain passage
                logger.warning('  post obsolète (DOM changé), nouvelle tentative au passage suivant')
            except ScraperError:
                raise
            except WebDriverException as error:
                translated = classify_exception(error)
                if translated is not None:
                    raise translated from error
                logger.warning('  erreur sur un post : %s', (str(error).splitlines() or [''])[0][:200])
            _return_to_profile(driver, friend, logger)
            if profile.post_count >= limits.max_posts_per_friend:
                logger.info('  Limite de %s posts atteinte', limits.max_posts_per_friend)
                break

        progressed = scroll_window_and_wait(
            driver, limits.scroll_step_pixels + random.randint(-80, 80),
            limits.scroll_pause_seconds)
        stalls = 0 if fresh else stalls + 1
        end_of_page = 0 if progressed else end_of_page + 1
        if not fresh:
            time.sleep(random.uniform(0.8, 1.6))    # laisse Facebook charger la suite du fil
        if scrolls % 5 == 0:
            raise_if_blocked(driver)

    logger.info('  Fin : %s scrolls, %s posts', scrolls, profile.post_count)
    if profile.post_count == 0:
        _explain_zero_posts(driver, settings, logger, result)
    if profile.photo_url:    # enregistrée même quand la limite de posts est atteinte
        result.photos.append({'photo_id': generate_id('photo_'), 'owner_id': profile.friend_id,
                              'url': profile.photo_url, 'photo_type': 'PROFIL'})


def _return_to_profile(driver, friend, logger) -> None:
    """Après un post, on doit être revenu sur le profil de l'AMI (jamais sur le mien ni ailleurs)."""
    try:
        url = driver.current_url or ''
    except WebDriverException:
        return
    if str(friend['friend_id']).lower() in url.lower():
        return
    logger.warning('  navigation hors du profil de l\'ami (%s) : retour sur %s', url[:90],
                   friend['profile_url'])
    safe_get(driver, friend['profile_url'], logger)
    wait_for_main(driver, 20)
    time.sleep(random.uniform(1.0, 2.0))
    close_overlays(driver)


def _explain_zero_posts(driver, settings: ScraperSettings, logger, result: ScrapeResult) -> None:
    """0 post lu : profil réellement vide, ou sélecteurs devenus faux ?

    On écrit un instantané (compteurs, texte visible, HTML du 1er article, capture) dans
    diagnostics/ pour pouvoir ajuster les sélecteurs. Si la page contient manifestement des posts
    (articles, liens permanents, messages) le résultat devient ERROR : l'ami n'est PAS enregistré
    avec un faux « 0 post » (ce qui fausserait le score) et sera re-tenté.
    """
    try:
        info = driver.execute_script(js.JS_DIAG_POSTS)
    except WebDriverException as error:
        translated = classify_exception(error)
        if translated is not None:
            raise translated from error
        return
    if not isinstance(info, dict):
        return
    seen = {key: info.get(key, 0) for key in
            ('articles', 'feed_units', 'story_message', 'old_message', 'permalinks')}
    logger.info('  Diagnostic 0 post : %s', seen)
    try:
        folder = Path(settings.paths.debug_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stem = ''.join(c if c.isalnum() or c in '._-' else '_' for c in result.profile.friend_id)
        (folder / f'profile_{stem}.json').write_text(
            json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
        driver.save_screenshot(str(folder / f'profile_{stem}.png'))
    except Exception as error:      # le diagnostic ne doit jamais faire échouer le scraping
        logger.debug('  diagnostic non écrit : %s', error)
    if any(int(v or 0) > 0 for v in seen.values()):
        result.status = Status.ERROR
        result.error = ('des publications sont affichées mais aucune n\'a pu être extraite '
                        f'({seen}) — voir diagnostics/')
        logger.warning('  %s', result.error)


def _process_post(driver, settings: ScraperSettings, logger, result: ScrapeResult,
                  article, text: str, date: str, link) -> None:
    kw, limits, features = settings.keywords, settings.limits, settings.features
    profile = result.profile
    post_id = generate_id('post_')
    scroll_before = driver.execute_script('return window.scrollY;')

    reactions, reactions_total, reactors = [], 0, []
    if features.reactions:
        try:
            found = extract_reactions(driver, article, post_id, kw, profile.friend_id, limits,
                                      with_reactors=features.reactors, logger=logger,
                                      debug_dir=settings.paths.debug_dir)
            reactions, reactions_total, reactors = found.reactions, found.total, found.reactors
        except (StaleElementReferenceException, WebDriverException) as error:
            translated = classify_exception(error)
            if translated is not None:
                raise translated from error
            logger.warning('    réactions non lues : %s', (str(error).splitlines() or [''])[0][:200])
        close_overlays(driver)
    comments = []
    if features.comments:
        try:
            comments = extract_comments(driver, link, post_id, profile.friend_id, limits, kw,
                                        logger, article=article)
        except (StaleElementReferenceException, WebDriverException) as error:
            translated = classify_exception(error)
            if translated is not None:
                raise translated from error
            logger.warning('    commentaires non lus : %s', (str(error).splitlines() or [''])[0][:200])
            close_overlays(driver)

    driver.execute_script('window.scrollTo(0, arguments[0]);', scroll_before)
    time.sleep(0.3)
    close_overlays(driver)

    result.posts.append(PostData(
        post_id=post_id, owner_id=profile.friend_id, text_content=text, date_text=date,
        reactions_total=reactions_total, comments_total=len(comments),
        reactions_detail=[{'type': r.reaction_type, 'count': r.count} for r in reactions]))
    result.reactions.extend(reactions)
    result.reactors.extend(reactors)
    result.comments.extend(comments)
    profile.post_count += 1
    profile.comment_count += len(comments)
    profile.reaction_count += reactions_total
    logger.info('    Post[%s] %s | %s comm | %s react%s', profile.post_count,
                text[:55].replace('\n', ' '), len(comments), reactions_total,
                f' ({len(reactors)} noms)' if features.reactors else '')
