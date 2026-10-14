import logging
import time

import pytest

from fb_modular.config.settings import ScraperSettings


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Les tests ne doivent jamais attendre pour de vrai."""
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)


@pytest.fixture
def logger():
    return logging.getLogger('fb_test')


@pytest.fixture
def settings(tmp_path):
    base = ScraperSettings.from_base_dir(tmp_path)
    return base.with_limits(pause_min=0, pause_max=0, batch_pause=0, batch_size=1000,
                            network_backoff_base=1, network_backoff_max=2)
