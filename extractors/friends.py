"""Extraction de la liste d'amis d'un compte Facebook.

Sur la page « Tous les amis » (friends/list) la liste est une colonne de GAUCHE qui a son propre
ascenseur, à côté d'un volet d'aperçu. Deux conséquences pour le code :
  - window.scrollBy ne fait rien : on fait défiler le conteneur de la liste ;
  - tous les <a> de la page ne sont pas des amis (notifications, menus...) : on filtre par
    structure (hors bandeau/dialogues, hors liens de notification) puis par validité d'URL et de nom.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..browser import js
from ..browser.page import (
    close_overlays, human_sleep, raise_if_blocked, raise_translated, safe_get, wait_for_main,
)
from ..config.settings import ScraperSettings
from ..core.errors import ScraperError
from ..core.models import Friend
from ..core.text_utils import (
    extract_facebook_id, extract_leading_number, is_notification_link, is_valid_display_name,
    normalise_facebook_url, normalise_space,
)

FRIEND_PAGES = (
    'https://www.facebook.com/friends/list',
    'https://www.facebook.com/me/friends',
    'https://www.facebook.com/friends',
)


def _is_cdn_image(url: str) -> bool:
    return 'scontent' in url or 'fbcdn' in url


def merge_candidates(raw_links: Iterable, found: Dict[str, dict], forbidden: set,
                     exclude_ids: set, max_friends: int) -> int:
    """Fusionne des liens bruts [href, texte, aria, img] dans `found` ({id: ami}).

    Plusieurs liens peuvent désigner le même ami (photo cliquable sans texte + nom cliquable) :
    on garde le meilleur nom et la première photo. Retourne le nombre de NOUVEAUX amis nommés.
    """
    added = 0
    for href, text, aria, image in raw_links:
        if is_notification_link(href):
            continue
        url = normalise_facebook_url(href)
        friend_id = extract_facebook_id(url, forbidden)
        if not friend_id or friend_id in exclude_ids:
            continue

        name = ''
        for candidate in (text, aria):
            candidate = normalise_space(candidate)
            if candidate and is_valid_display_name(candidate, friend_id, forbidden):
                name = candidate
                break

        entry = found.get(friend_id)
        if entry is None:
            if len(found) >= max_friends * 2:     # garde-fou mémoire
                continue
            entry = {'friend_id': friend_id, 'display_name': '', 'profile_url': url,
                     'photo_url': '', 'raw_href': href}
            found[friend_id] = entry
        if name and not entry['display_name']:
            entry['display_name'] = name
            added += 1
        if image and not entry['photo_url'] and _is_cdn_image(image):
            entry['photo_url'] = image
    return added


def _named(found: Dict[str, dict]) -> List[dict]:
    return [entry for entry in found.values() if entry['display_name']]


def _scroll_list(driver, step: int, hint: str, wait: float):
    """Fait défiler la liste. Retourne (a_bougé, est_en_bas)."""
    before = driver.execute_script(js.JS_FRIEND_SCROLL, 0, hint)
    driver.execute_script(js.JS_FRIEND_SCROLL, step, hint)
    human_sleep(0.4)
    after = driver.execute_script(js.JS_FRIEND_SCROLL, 0, hint)
    deadline = time.time() + wait
    while after[2] == before[2] and time.time() < deadline:
        at_bottom = after[1] + after[3] >= after[2] - 5
        if after[1] != before[1] and not at_bottom:
            break                                # du contenu déjà chargé reste à lire
        time.sleep(0.3)
        after = driver.execute_script(js.JS_FRIEND_SCROLL, 0, hint)
    if after[2] != before[2]:
        human_sleep(0.4)                         # laisse Facebook finir d'afficher les lignes
        after = driver.execute_script(js.JS_FRIEND_SCROLL, 0, hint)
    at_bottom = after[1] + after[3] >= after[2] - 5
    moved = after[1] != before[1] or after[2] != before[2]
    return moved, at_bottom


def dump_friend_diagnostics(driver, debug_dir: Path, logger) -> None:
    """Écrit un instantané (liens + conteneurs + capture) pour comprendre une page inattendue."""
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        anchors = driver.execute_script(js.JS_DIAG_ANCHORS) or []
        (debug_dir / 'friends_anchors.json').write_text(
            json.dumps({'url': driver.current_url, 'anchors': anchors}, ensure_ascii=False, indent=1),
            encoding='utf-8')
        driver.save_screenshot(str(debug_dir / 'friends_page.png'))
        logger.error('Diagnostic écrit dans %s (friends_anchors.json + friends_page.png)', debug_dir)
    except Exception as error:
        logger.warning('Diagnostic impossible : %s', error)


def extract_all_friends(driver, settings: ScraperSettings, logger,
                        exclude_ids: Optional[set] = None) -> List[dict]:
    limits, forbidden = settings.limits, settings.keywords.forbidden_ids
    exclude_ids = set(exclude_ids or ())
    found: Dict[str, dict] = {}
    logger.info('Extraction de la liste des amis...')

    try:
        # 1) Chargement : on essaie plusieurs URL jusqu'à voir de vrais amis.
        for url in FRIEND_PAGES:
            safe_get(driver, url, logger)
            wait_for_main(driver, 15)
            human_sleep(2.0)
            raise_if_blocked(driver)
            close_overlays(driver)
            raw = driver.execute_script(js.JS_FRIEND_ANCHORS) or []
            merge_candidates(raw, found, forbidden, exclude_ids, limits.max_friends_total)
            logger.info('  %s : %s liens, %s amis reconnus', url, len(raw), len(_named(found)))
            if _named(found):
                break
        if not _named(found):
            logger.error("Aucun ami reconnu : la structure de la page a peut-être changé.")
            dump_friend_diagnostics(driver, settings.paths.debug_dir, logger)
            return []

        expected = extract_leading_number(driver.execute_script(js.JS_EXPECTED_TOTAL) or '')
        if expected and expected < len(_named(found)):
            # Total incohérent (ex. badge « 1 » du menu) : on l'ignore et on défile jusqu'à épuisement.
            logger.warning('  Total annoncé (%s) < amis déjà vus (%s) : ignoré', expected,
                           len(_named(found)))
            expected = 0
        if expected:
            logger.info('  Facebook annonce %s amis', expected)
        hint = _named(found)[0]['raw_href']

        # 2) Défilement du conteneur de liste jusqu'à épuisement.
        stalls, scrolls, last_logged = 0, 0, 0
        while (stalls < limits.friends_stall_limit and scrolls < limits.max_scrolls_friends
               and len(_named(found)) < limits.max_friends_total):
            raw = driver.execute_script(js.JS_FRIEND_ANCHORS) or []
            added = merge_candidates(raw, found, forbidden, exclude_ids, limits.max_friends_total)
            total = len(_named(found))
            if expected and total >= int(expected * 0.995):
                break
            moved, at_bottom = _scroll_list(driver, int(limits.scroll_step_pixels * random.uniform(0.7, 1.0)), hint,
                                            limits.scroll_pause_seconds)
            scrolls += 1
            stalls = 0 if (added or (moved and not at_bottom)) else stalls + 1
            if total - last_logged >= 100:
                logger.info('  %s amis (scroll %s)%s', total, scrolls,
                            f' / ~{expected}' if expected else '')
                last_logged = total
            if scrolls % 25 == 0:
                raise_if_blocked(driver)
    except ScraperError:
        raise
    except Exception as error:
        raise_translated(error)

    friends = [asdict(Friend(friend_id=e['friend_id'], display_name=e['display_name'],
                             profile_url=e['profile_url'], photo_url=e['photo_url']))
               for e in _named(found)][:limits.max_friends_total]
    coverage = f' ({100 * len(friends) / expected:.0f} % des {expected} annoncés)' if expected else ''
    logger.info('Total amis trouvés : %s en %s scrolls%s', len(friends), scrolls, coverage)
    if expected and len(friends) < expected * 0.9:
        logger.warning("Liste incomplète : relancez avec --refresh-friends ou vérifiez la page.")
    return friends
