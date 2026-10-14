"""Création et configuration du navigateur (undetected-chromedriver)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import undetected_chromedriver as uc

PAGE_LOAD_TIMEOUT = 60      # secondes ; au-delà on arrête le chargement et on continue
SCRIPT_TIMEOUT = 60
COMMAND_TIMEOUT = 90        # lecture HTTP vers chromedriver (défaut Selenium : 120 s)


def create_browser(profile_dir: Path, headless: bool = False, no_sandbox: bool = False,
                   chrome_version: int | None = None) -> uc.Chrome:
    options = uc.ChromeOptions()
    options.add_argument(f'--user-data-dir={profile_dir}')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-blink-features=AutomationControlled')   # rétabli (ta v1)
    options.add_argument('--disable-notifications')
    if no_sandbox:                       # uniquement si Chrome tourne en root
        options.add_argument('--no-sandbox')
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1366,900')
    else:
        options.add_argument('--start-maximized')
    # 'eager' : get() rend la main dès que le DOM est prêt (pas d'attente des images/pubs).
    options.page_load_strategy = 'eager'
    options.add_experimental_option('prefs', {
        'profile.default_content_setting_values.notifications': 2,
    })

    kwargs = {'options': options}
    if chrome_version:                   # sinon : détection automatique de la version de Chrome
        kwargs['version_main'] = chrome_version
    driver = uc.Chrome(**kwargs)

    try:   # rétabli (ta v1) : navigator.webdriver n'est plus exposé aux pages
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})
    except Exception:
        pass

    for setter, value in ((driver.set_page_load_timeout, PAGE_LOAD_TIMEOUT),
                          (driver.set_script_timeout, SCRIPT_TIMEOUT)):
        try:
            setter(value)
        except Exception:
            pass
    try:   # selon la version de Selenium, l'attribut a changé de nom
        driver.command_executor._client_config.timeout = COMMAND_TIMEOUT
    except Exception:
        try:
            driver.command_executor.set_timeout(COMMAND_TIMEOUT)
        except Exception:
            pass
    return driver


def safe_quit(driver: Optional[uc.Chrome]) -> None:
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass
