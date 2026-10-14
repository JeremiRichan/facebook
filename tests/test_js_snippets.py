"""Teste les snippets JavaScript sur du HTML simulé (jsdom). Ignoré si node/jsdom sont absents.

Installation (une fois) :  cd fb_modular/tests && npm install jsdom
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from fb_modular.browser import js

HERE = Path(__file__).parent
HARNESS = HERE / 'js_harness.js'


def _jsdom_available() -> bool:
    if not shutil.which('node'):
        return False
    env = dict(os.environ)
    probe = subprocess.run(['node', '-e', f"require({json.dumps(os.environ.get('JSDOM_PATH', 'jsdom'))})"],
                           cwd=HERE, capture_output=True, env=env)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _jsdom_available(), reason='node + jsdom requis (npm install jsdom)')


@pytest.fixture(scope='module')
def js_results():
    completed = subprocess.run(['node', str(HARNESS)], cwd=HERE, capture_output=True, text=True,
                               input=json.dumps({'snippets': js.ALL_SNIPPETS}), timeout=120)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_every_snippet_parses():
    """Une faute de syntaxe JS ne se verrait qu'en production : on les compile toutes."""
    script = ("const s=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "for (const [k,v] of Object.entries(s)) { try { new Function(v); } catch(e) { console.log(k+': '+e.message); process.exit(1);} }")
    completed = subprocess.run(['node', '-e', script], input=json.dumps(js.ALL_SNIPPETS),
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_js_scenarios(js_results):
    failures = [f'{name} -> {detail}' for name, ok, detail in js_results if not ok]
    assert len(js_results) >= 25
    assert not failures, '\n'.join(failures)
