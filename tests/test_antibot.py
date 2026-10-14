"""Protections anti-détection héritées de la v1 et pauses variables : elles ne doivent plus disparaître."""

import random
import re
from pathlib import Path

from fb_modular.browser import driver_factory
from fb_modular.browser.page import jitter

PACKAGE = Path(__file__).resolve().parents[1]


class FakeChrome:
    last = None

    def __init__(self, **kwargs):
        FakeChrome.last, self.kwargs, self.cdp = self, kwargs, []

    def execute_cdp_cmd(self, name, params):
        self.cdp.append((name, params))

    def set_page_load_timeout(self, v):
        pass

    def set_script_timeout(self, v):
        pass


def make(monkeypatch, tmp_path, **kwargs):
    monkeypatch.setattr(driver_factory.uc, 'Chrome', FakeChrome)
    driver_factory.create_browser(tmp_path / 'profile', **kwargs)
    return FakeChrome.last


def test_automation_flag_is_disabled(monkeypatch, tmp_path):
    chrome = make(monkeypatch, tmp_path)
    assert '--disable-blink-features=AutomationControlled' in chrome.kwargs['options'].arguments


def test_navigator_webdriver_is_hidden_on_every_new_document(monkeypatch, tmp_path):
    chrome = make(monkeypatch, tmp_path)
    names = [name for name, _ in chrome.cdp]
    assert 'Page.addScriptToEvaluateOnNewDocument' in names
    source = next(p['source'] for n, p in chrome.cdp if n == 'Page.addScriptToEvaluateOnNewDocument')
    assert "navigator,'webdriver'" in source and 'undefined' in source


def test_persistent_profile_keeps_the_real_session(monkeypatch, tmp_path):
    chrome = make(monkeypatch, tmp_path)
    assert any(a.startswith('--user-data-dir=') and a.endswith('profile') for a in chrome.kwargs['options'].arguments)


def test_chrome_version_is_automatic_unless_forced(monkeypatch, tmp_path):
    assert 'version_main' not in make(monkeypatch, tmp_path).kwargs
    assert make(monkeypatch, tmp_path, chrome_version=155).kwargs['version_main'] == 155


def test_no_sandbox_only_on_request(monkeypatch, tmp_path):
    assert '--no-sandbox' not in make(monkeypatch, tmp_path).kwargs['options'].arguments
    assert '--no-sandbox' in make(monkeypatch, tmp_path, no_sandbox=True).kwargs['options'].arguments


def test_jitter_varies_and_stays_in_bounds():
    random.seed(1)
    values = [jitter(1.0) for _ in range(200)]
    assert all(0.6 <= v <= 1.4 for v in values) and len(set(values)) > 150


def test_javascript_never_clicks_by_itself():
    """Les clics instantanés en JS (événements non fiables, en rafale) sont proscrits."""
    source = (PACKAGE / 'browser' / 'js.py').read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', source)
    assert '.click()' not in code


def test_no_fixed_sleep_in_the_interaction_loops():
    """Dans les boucles de commentaires / réactions / amis, les pauses passent par human_sleep."""
    for name in ('posts.py', 'friends.py'):
        text = (PACKAGE / 'extractors' / name).read_text(encoding='utf-8')
        fixed = re.findall(r'time\.sleep\((?:[2-9]|1\.[0-9])[^)]*\)', text)      # pauses >= 1 s fixes
        assert not fixed, f'{name}: pause fixe >= 1 s : {fixed}'
