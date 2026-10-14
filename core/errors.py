"""Exceptions métier et classification des erreurs Selenium/réseau."""

from __future__ import annotations


class ScraperError(Exception):
    """Erreur de base."""


class NetworkError(ScraperError):
    """Problème réseau transitoire (timeout, DNS, connexion coupée) : on réessaie plus tard."""


class BlockedError(ScraperError):
    """Checkpoint, page de connexion, limitation Facebook : il faut arrêter proprement."""


class BrowserClosedError(ScraperError):
    """Le navigateur a été fermé ou a planté."""


_CLOSED = (
    'invalid session id', 'no such window', 'target window already closed',
    'not connected to devtools', 'chrome not reachable', 'session deleted',
    'web view not found', 'browser has closed', 'disconnected:',
)
_NETWORK = (
    'err_connection', 'err_internet_disconnected', 'err_name_not_resolved', 'err_timed_out',
    'err_network_changed', 'err_proxy', 'err_tunnel', 'err_address_unreachable',
    'err_empty_response', 'err_ssl', 'read timed out', 'readtimeout', 'connection aborted',
    'connection refused', 'max retries exceeded', 'timed out receiving message',
)


def classify_exception(exc: BaseException) -> ScraperError | None:
    """Traduit une exception brute en erreur métier (ou None si inconnue)."""
    if isinstance(exc, ScraperError):
        return exc
    text = f'{type(exc).__name__} {exc}'.lower()
    first_line = (str(exc).splitlines() or [''])[0]
    if any(marker in text for marker in _CLOSED):
        return BrowserClosedError(first_line or 'navigateur fermé')
    if any(marker in text for marker in _NETWORK):
        return NetworkError(first_line or 'erreur réseau')
    return None
