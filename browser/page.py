"""Utilitaires de navigation : chargement sûr, attentes adaptatives, détection de blocage."""

from __future__ import annotations

import random
import time
from typing import Any, List, Optional

from selenium.common.exceptions import (
    ElementClickInterceptedException, TimeoutException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from ..core.errors import BlockedError, BrowserClosedError, ScraperError, classify_exception
from . import js

URL_BLOCK_SIGNS = ('checkpoint', '/login', 'login.php', 'two_step_verification', '/recover',
                   'account_disabled', 'ad_account_locked')


def pause(minimum: float = 2.0, maximum: float = 4.0) -> None:
    time.sleep(random.uniform(minimum, maximum))


def jitter(base: float, spread: float = 0.4) -> float:
    """Durée aléatoire autour de `base` (±40 % par défaut) : jamais deux pauses identiques."""
    return random.uniform(base * (1 - spread), base * (1 + spread))


def human_sleep(base: float, spread: float = 0.4) -> None:
    time.sleep(jitter(base, spread))


def raise_translated(exc: BaseException) -> None:
    """Relance `exc` sous forme d'erreur métier si on sait la classer, sinon telle quelle."""
    translated = classify_exception(exc)
    if translated is not None:
        raise translated from exc
    raise exc


def safe_get(driver, url: str, logger=None) -> None:
    """driver.get() qui ne bloque plus : un timeout de chargement n'est pas fatal.

    - TimeoutException (page lente) : on stoppe le chargement et on continue, le DOM est
      souvent déjà exploitable.
    - Coupure réseau / navigateur fermé : NetworkError / BrowserClosedError.
    """
    try:
        driver.get(url)
    except TimeoutException:
        if logger:
            logger.warning('  Chargement lent, on continue : %s', url)
        try:
            driver.execute_script('window.stop();')
        except WebDriverException:
            pass
    except ScraperError:
        raise
    except Exception as exc:  # WebDriverException, urllib3 ReadTimeoutError...
        raise_translated(exc)


def detect_block(driver) -> Optional[str]:
    """Retourne une raison si la page est un blocage / une demande de connexion, sinon None."""
    try:
        url = driver.current_url.lower()
    except Exception as exc:
        translated = classify_exception(exc)
        return f'navigateur fermé ({translated})' if translated else None
    for sign in URL_BLOCK_SIGNS:
        if sign in url:
            return f'page de connexion/blocage ({sign})'
    try:
        info = driver.execute_script(js.JS_BLOCK_CHECK) or {}
    except Exception:
        return None
    if info.get('login'):
        return 'formulaire de connexion affiché (session expirée ?)'
    if info.get('blocked'):
        return 'Facebook limite temporairement le compte'
    return None


def raise_if_blocked(driver) -> None:
    reason = detect_block(driver)
    if reason:
        if reason.startswith('navigateur fermé'):
            raise BrowserClosedError(reason)
        raise BlockedError(reason)


def wait_for_main(driver, timeout: float = 15.0) -> None:
    """Attend la fin du chargement et la présence de la zone principale (sans lever d'erreur)."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                'return document.readyState !== "loading" && '
                '!!document.querySelector(\'div[role="main"]\');'))
    except TimeoutException:
        pass


# --------------------------------------------------------------------------- dialogues

def visible_dialogs(driver) -> List[Any]:
    try:
        return driver.execute_script(js.JS_DIALOGUES) or []
    except WebDriverException:
        return []


def wait_for_dialogs(driver, timeout: float = 3.0) -> List[Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        dialogs = visible_dialogs(driver)
        if dialogs:
            return dialogs
        time.sleep(0.2)
    return []


def close_overlays(driver) -> None:
    """Ferme les fenêtres modales ouvertes (bouton Fermer, sinon touche Échap)."""
    for _ in range(3):
        if not visible_dialogs(driver):
            return
        try:
            buttons = driver.execute_script(js.JS_FERMER) or []
            clicked = [click_element(driver, button) for button in buttons]
            if not any(clicked):
                driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        except WebDriverException:
            pass
        human_sleep(0.35)


def click_element(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except (ElementClickInterceptedException, WebDriverException):
        pass
    try:
        driver.execute_script('arguments[0].click();', element)
        return True
    except WebDriverException:
        return False


# ----------------------------------------------------------------------------- défilement

def scroll_window_and_wait(driver, step: int, max_wait: float) -> bool:
    """Fait défiler la page et n'attend que si c'est nécessaire.

    Retourne True si on a progressé (nouveau contenu ou position changée).
    """
    y0, h0 = driver.execute_script('return [window.scrollY, document.body.scrollHeight];')
    driver.execute_script('window.scrollBy(0, arguments[0]);', step)
    time.sleep(0.25)
    y1, h1, view = driver.execute_script(
        'return [window.scrollY, document.body.scrollHeight, window.innerHeight];')
    if y1 - y0 > 50 and y1 + view < h1 - 400:
        return True                      # du contenu déjà chargé reste en dessous : pas d'attente
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(0.3)
        if driver.execute_script('return document.body.scrollHeight;') != h0:
            time.sleep(0.5)
            return True
    return abs(driver.execute_script('return window.scrollY;') - y0) > 50
