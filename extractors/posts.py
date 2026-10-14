"""Extraction des réactions et des commentaires d'un post."""

from __future__ import annotations

import json
import re
import time
import uuid
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from ..browser import js
from ..browser.page import (
    click_element, close_overlays, human_sleep, visible_dialogs, wait_for_dialogs,
)
from ..config.settings import KeywordSets, ScrapingLimits
from ..core.errors import classify_exception
from ..core.models import CommentData, ReactionSummary, ReactorData
from ..core.text_utils import (
    extract_facebook_id, extract_leading_number, is_valid_display_name, normalise_facebook_url,
    normalise_reaction_label, normalise_space,
)

_AUTHOR_FROM_ARIA = re.compile(
    r'(?:commentaire de|comment by|comment from|réponse de|reply by|reply from)\s+(.+?)(?:\s*[:·]|$)',
    re.IGNORECASE)


def generate_id(prefix: str) -> str:
    return f'{prefix}{uuid.uuid4().hex[:12]}'


def _reraise_fatal(error: BaseException) -> None:
    """Navigateur fermé / réseau coupé : on remonte (ne pas avaler dans un except générique)."""
    translated = classify_exception(error)
    if translated is not None:
        raise translated from error


# ----------------------------------------------------------------------------- réactions

@dataclass
class ReactionsResult:
    reactions: List[ReactionSummary] = field(default_factory=list)
    total: int = 0
    reactors: List[ReactorData] = field(default_factory=list)


def _is_all_tab(label: str) -> bool:
    return label.lower().startswith(('tous', 'all', 'todos', 'alle', 'tutti'))


def _merge_reactor_rows(rows, seen: Dict[str, ReactorData], post_id: str, owner_id: str,
                        reaction_type: str, keywords: KeywordSets, limit: int) -> int:
    """Ajoute les personnes lues. Une personne n'a QU'UNE réaction : la première trouvée gagne
    (une ligne résiduelle de l'onglet précédent ne sera donc pas reclassée). Retourne le nombre
    de nouvelles personnes."""
    added = 0
    for href, text, aria in rows:
        if len(seen) >= limit:
            break
        url = normalise_facebook_url(href)
        reactor_id = extract_facebook_id(url, keywords.forbidden_ids)
        if not reactor_id or reactor_id in seen:
            continue
        name = ''
        for candidate in (text, aria):
            candidate = normalise_space(candidate)
            if candidate and is_valid_display_name(candidate, reactor_id, keywords.forbidden_ids):
                name = candidate
                break
        if not name:
            continue
        seen[reactor_id] = ReactorData(post_id, owner_id, reactor_id, name, url, reaction_type)
        added += 1
    return added


def extract_reactors(driver, dialog, post_id: str, owner_id: str, tab_labels: List[str],
                     limits: ScrapingLimits, keywords: KeywordSets) -> List[ReactorData]:
    """Lit, dans la fenêtre des réactions déjà ouverte, QUI a réagi et avec quel type.

    On ouvre chaque onglet par type (J'aime, J'adore...) et on fait défiler sa liste. Sans onglets
    par type, on lit la liste par défaut avec le type 'unknown'.
    """
    seen: Dict[str, ReactorData] = {}
    cap = limits.max_reactors_per_post
    targets = [(index, normalise_reaction_label(label)) for index, label in enumerate(tab_labels)
               if not _is_all_tab(label)]
    targets = [(index, rtype) for index, rtype in targets if rtype]

    def read_current_list(reaction_type: str) -> None:
        stalls = 0
        for _ in range(30):
            rows = driver.execute_script(js.JS_REACTOR_ROWS, dialog) or []
            added = _merge_reactor_rows(rows, seen, post_id, owner_id, reaction_type, keywords, cap)
            if len(seen) >= cap:
                return
            driver.execute_script(js.JS_SCROLL_ZONE, dialog)
            human_sleep(0.5)
            stalls = 0 if added else stalls + 1
            if stalls >= 3:
                return

    if not targets:
        read_current_list('unknown')
        return list(seen.values())

    for index, reaction_type in targets:
        if len(seen) >= cap:
            break
        tab = driver.execute_script(js.JS_CLICK_TAB, dialog, index)
        if tab is None or not click_element(driver, tab):
            continue
        for _ in range(8):                       # attend que l'onglet soit réellement actif
            human_sleep(0.25)
            if driver.execute_script(js.JS_TAB_SELECTED, dialog, index) is not False:
                break
        human_sleep(0.6)                         # laisse la nouvelle liste remplacer l'ancienne
        read_current_list(reaction_type)
    return list(seen.values())


_DUMPED = {'n': 0}


def _dump_dialog(driver, dialog, post_id: str, logger, debug_dir) -> None:
    """Aucun réacteur lu alors qu'une fenêtre est ouverte : on garde son HTML (3 fichiers max)."""
    if debug_dir is None or _DUMPED['n'] >= 3:
        return
    try:
        info = driver.execute_script(js.JS_DIALOG_HTML, dialog)
        if not isinstance(info, dict):
            return
        _DUMPED['n'] += 1
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        path = Path(debug_dir) / f'reactions_dialog_{_DUMPED["n"]}.json'
        path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
        if logger is not None:
            logger.warning('    aucun réacteur lu : fenêtre enregistrée dans %s', path)
    except Exception:
        pass


def extract_reactions(driver, article, post_id: str, keywords: KeywordSets,
                      owner_id: str = '', limits: ScrapingLimits | None = None,
                      with_reactors: bool = False, logger=None,
                      debug_dir: Path | None = None) -> ReactionsResult:
    """Compteurs par type (et, avec with_reactors, les personnes qui ont réagi).

    Le total est celui de l'onglet « Tous » s'il existe (sinon la somme des types).
    """
    result = ReactionsResult()
    seen: set = set()
    total_all = 0

    def add(reaction_type, count: int) -> None:
        if reaction_type and reaction_type not in seen and count > 0:
            seen.add(reaction_type)
            result.reactions.append(
                ReactionSummary(generate_id('react_'), post_id, reaction_type, count))

    try:
        button = driver.execute_script(
            js.JS_BOUTON_REACTIONS, article, keywords.reaction_exclusion_words,
            keywords.reaction_type_regex, keywords.who_reacted_regex)
        if button is not None and click_element(driver, button):
            for dialog in wait_for_dialogs(driver, 3.0):
                labels = driver.execute_script(js.JS_ONGLETS, dialog) or []
                for label in labels:
                    if _is_all_tab(label):
                        total_all = max(total_all, extract_leading_number(label))
                        continue
                    add(normalise_reaction_label(label), extract_leading_number(label))
                if with_reactors and limits is not None:
                    # Sans onglets par type (interface qui change), on lit la liste par défaut.
                    found = extract_reactors(driver, dialog, post_id, owner_id, labels,
                                             limits, keywords)
                    if len(found) > len(result.reactors):
                        result.reactors = found
                    if logger is not None:
                        logger.info('    réacteurs : %s onglet(s) %s -> %s nom(s)',
                                    len(labels), [normalise_space(x)[:18] for x in labels][:6],
                                    len(found))
                    if not found:
                        _dump_dialog(driver, dialog, post_id, logger, debug_dir)
            close_overlays(driver)
    except StaleElementReferenceException:
        raise
    except WebDriverException as error:
        _reraise_fatal(error)
        close_overlays(driver)

    if not result.reactions:   # repli : étiquettes visibles directement dans le post
        try:
            for label in driver.execute_script(
                    js.JS_LABELS_REACTIONS, article, keywords.reaction_exclusion_words,
                    keywords.reaction_type_regex) or []:
                add(normalise_reaction_label(label), extract_leading_number(label) or 1)
        except StaleElementReferenceException:
            raise
        except WebDriverException as error:
            _reraise_fatal(error)

    result.total = total_all or sum(item.count for item in result.reactions)
    return result


# --------------------------------------------------------------------------- commentaires

def _open_post(driver, permalink) -> str | None:
    """Clique le lien du post. Retourne 'modal', 'page' ou None si rien ne s'est ouvert."""
    url_before = driver.current_url
    if not click_element(driver, permalink):
        return None
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if visible_dialogs(driver):
            return 'modal'
        if driver.current_url != url_before:
            human_sleep(1.5)
            return 'page'
        time.sleep(0.2)
    return None


def _same_page(a: str, b: str) -> bool:
    """Même page, sans tenir compte du sous-domaine (www/web), du « / » final ni des paramètres
    de suivi ; profile.php est distingué par son ?id=."""
    def key(url: str):
        parsed = urlparse(url or '')
        path = parsed.path.rstrip('/').lower()
        ident = parse_qs(parsed.query).get('id', [''])[0] if path.endswith('profile.php') else ''
        return path, ident
    return key(a) == key(b)


def _restore_page(driver, url_before: str, logger) -> None:
    """Revient exactement sur la page d'avant l'ouverture du post.

    Fermer la visionneuse de Facebook revient déjà en arrière : un `back()` systématique remontait
    deux fois dans l'historique (jusqu'à VOTRE profil). On ne recule donc que si on n'est pas déjà
    revenu, et un seul pas ; au besoin on recharge l'URL d'origine.
    """
    if not url_before or _same_page(driver.current_url, url_before):
        return
    driver.back()
    human_sleep(1.5)
    if not _same_page(driver.current_url, url_before):
        logger.info('    retour direct sur %s', url_before[:90])
        driver.get(url_before)
        human_sleep(2.0)


def extract_comments(driver, permalink, post_id: str, owner_id: str, limits: ScrapingLimits,
                     keywords: KeywordSets, logger, article=None) -> List[CommentData]:
    comments: List[CommentData] = []
    if permalink is None and article is not None:
        # Pas de lien permanent visible : on tente le compteur « N commentaires » du post.
        try:
            permalink = driver.execute_script(js.JS_BOUTON_COMMENTAIRES, article,
                                              keywords.comment_count_regex)
        except StaleElementReferenceException:
            permalink = None
        except WebDriverException as error:
            _reraise_fatal(error)
            permalink = None
    if permalink is None:
        return comments

    try:
        url_before = driver.current_url
    except WebDriverException:
        url_before = ''
    mode = _open_post(driver, permalink)
    if mode is None:
        # Ni fenêtre ni navigation : lire la page maintenant attribuerait au post les commentaires
        # d'autres publications (comportement de la v1). On ne lit rien.
        logger.debug('    post non ouvert : commentaires ignorés')
        return comments

    root = visible_dialogs(driver)[-1] if mode == 'modal' else None
    try:
        logger.info('    post ouvert en %s : %s', mode, driver.current_url[:100])
    except WebDriverException:
        pass
    try:
        # « Plus pertinents » -> « Tous les commentaires » (une seule fois)
        sort_button = driver.execute_script(js.JS_TRI_PERTINENTS, root, keywords.sort_button_regex)
        if sort_button is not None and click_element(driver, sort_button):
            human_sleep(0.7)
            all_option = driver.execute_script(js.JS_TRI_TOUS, keywords.all_comments_regex)
            if all_option is not None and click_element(driver, all_option):
                human_sleep(1.0)

        seen: set = set()
        stalls, last_height, ended_by_limit = 0, -1, True
        for _ in range(limits.max_comment_passes):
            clicks = 0
            for button in driver.execute_script(js.JS_EXPAND, root, keywords.expansion_regex, 3) or []:
                if click_element(driver, button):         # clic Selenium, un à la fois
                    clicks += 1
                human_sleep(0.55)
            if clicks:
                human_sleep(0.8)
            rows = driver.execute_script(js.JS_LIRE_COMMS, root, keywords.comment_prefixes) or []

            fresh = 0
            for author, text, date, aria in rows:
                if not author and aria:
                    match = _AUTHOR_FROM_ARIA.search(aria)
                    author = match.group(1).strip()[:80] if match else ''
                if not text:
                    continue
                key = (author + '|' + text)[:160]
                if key in seen:
                    continue
                seen.add(key)
                comments.append(CommentData(generate_id('comm_'), post_id, owner_id, text,
                                            author, date))
                fresh += 1
                if len(comments) >= limits.max_comments_per_post:
                    break
            if len(comments) >= limits.max_comments_per_post:
                ended_by_limit = False
                break

            height = driver.execute_script(js.JS_SCROLL_ZONE, root)
            human_sleep(0.7)
            if fresh == 0 and not clicks and height == last_height:
                stalls += 1
                if stalls >= 3:
                    ended_by_limit = False
                    break
            else:
                stalls = 0
            last_height = height
        if ended_by_limit:
            logger.warning('    commentaires : limite de %s passes atteinte (%s lus) — post '
                           'peut-être incomplet ; augmentez max_comment_passes',
                           limits.max_comment_passes, len(comments))
    except StaleElementReferenceException:
        pass                       # le DOM a changé : on garde ce qui a déjà été lu
    except WebDriverException as error:
        _reraise_fatal(error)
        logger.debug('    erreur commentaires : %s', error)
    finally:
        try:
            close_overlays(driver)
            _restore_page(driver, url_before, logger)
        except Exception:          # navigateur déjà fermé : rien à nettoyer
            pass
    return comments
