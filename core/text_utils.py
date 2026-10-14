"""Fonctions pures de normalisation (URL, identifiants, noms, nombres)."""

from __future__ import annotations

import re

# Segments d'URL qui ne sont JAMAIS un profil (routes de l'application).
DEFAULT_FORBIDDEN_IDS = frozenset({
    'friends', 'messages', 'message', 'home', 'watch', 'marketplace', 'market', 'groups', 'group',
    'events', 'event', 'pages', 'page', 'gaming', 'list', 'settings', 'notifications',
    'notification', 'permalink', 'about', 'photos', 'photo', 'videos', 'video', 'people', 'help',
    'privacy', 'terms', 'logout', 'create', 'add', 'new', 'birthdays', 'start', 'reels', 'reel',
    'search', 'saved', 'fundraisers', 'offers', 'ads', 'manager', 'login', 'recover',
    'checkpoint', 'dialog', 'ajax', 'plugins', 'sharer', 'memories', 'memory', 'gifs', 'stories',
    'story', 'me', 'policies', 'business', 'careers', 'cookies', 'bookmarks', 'onthisday',
    'professional_dashboard', 'profile', 'hashtag', 'lite', 'l.php', 'flx', 'privacy_center',
})

_FILE_EXTENSIONS = ('.php', '.html', '.htm', '.jsp', '.aspx', '.js', '.css', '.png', '.jpg',
                    '.jpeg', '.gif', '.svg', '.ico', '.json', '.xml', '.txt')

# Pseudo Facebook : lettres, chiffres, points, tirets. Les points sont FRÉQUENTS (jean.dupont.12).
_USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]{2,79}$')

_HOST_RE = r'^https?://(?:[\w-]+\.)*facebook\.com(?::\d+)?(?=[/?#]|$)'

_NOTIFICATION_RE = re.compile(r'(?:notif_id|notif_t|[?&]ref=notif)', re.IGNORECASE)


def normalise_facebook_url(raw_href: str | None) -> str:
    """Ramène n'importe quel lien Facebook (www, web, m...) à https://www.facebook.com/...

    profile.php conserve son ?id= (sans lui le profil est perdu). Retourne '' si ce n'est pas
    un lien Facebook.
    """
    if not raw_href:
        return ''
    raw = raw_href.strip()
    match = re.match(_HOST_RE, raw, re.IGNORECASE)
    if match:
        rest = raw[match.end():]
    elif raw.startswith('/') and not raw.startswith('//'):
        rest = raw
    else:
        return ''
    rest = rest.split('#')[0]
    path, _, query = rest.partition('?')
    path = path.rstrip('/')
    if path.lower().endswith('profile.php'):
        id_match = re.search(r'(?:^|&)id=(\d+)', query)
        if not id_match:
            return ''
        return f'https://www.facebook.com/profile.php?id={id_match.group(1)}'
    return 'https://www.facebook.com' + path


def is_notification_link(href: str | None) -> bool:
    """Vrai pour les liens de la cloche de notifications (…notif_id=…, ref=notif)."""
    return bool(href and _NOTIFICATION_RE.search(href))


def extract_facebook_id(url: str | None, forbidden_ids=None, strict: bool = True) -> str | None:
    """Extrait l'identifiant d'un profil (pseudo ou id numérique) depuis une URL.

    strict=True : seules les URL de racine de profil sont acceptées (/pseudo, /profile.php?id=,
    /people/Nom/ID). Les liens /pseudo/posts/..., /pseudo/photos... ne sont pas des amis.
    """
    if not url:
        return None
    forbidden = set(DEFAULT_FORBIDDEN_IDS)
    forbidden.update(str(item).lower() for item in (forbidden_ids or ()))

    base = url.split('#')[0]
    path_part, _, query = base.partition('?')
    path = re.sub(_HOST_RE, '', path_part, flags=re.IGNORECASE).rstrip('/')
    segments = [segment for segment in path.split('/') if segment]
    if not segments:
        return None

    first = segments[0].lower()
    if first == 'profile.php':
        match = re.search(r'(?:^|&)id=(\d+)', query)
        return match.group(1) if match else None
    if first == 'people':
        if len(segments) >= 3 and segments[-1].isdigit():
            return segments[-1]
        return None
    if strict and len(segments) > 1:
        return None

    candidate = segments[0]
    lowered = candidate.lower()
    if lowered in forbidden or lowered.startswith('pfbid'):
        return None
    if lowered.endswith(_FILE_EXTENSIONS):
        return None
    if not _USERNAME_RE.match(candidate) or candidate.endswith('.'):
        return None
    return candidate


def profile_url_from_id(friend_id: str) -> str:
    if friend_id.isdigit():
        return f'https://www.facebook.com/profile.php?id={friend_id}'
    return f'https://www.facebook.com/{friend_id}'


def is_valid_stored_id(friend_id: str) -> bool:
    """Vérifie qu'un id déjà stocké dans les CSV correspond à un vrai profil."""
    if friend_id == '__moi__':
        return True
    return extract_facebook_id(profile_url_from_id(friend_id)) == friend_id


# --------------------------------------------------------------------------- noms

NAV_LABELS = frozenset({
    'ami', 'amis', 'friend', 'friends', 'message', 'messages', 'accueil', 'home', 'photo',
    'photos', 'video', 'videos', 'vidéo', 'vidéos', 'profil', 'profile', 'settings',
    'paramètres', 'voir le profil', 'view profile', 'ajouter', 'add friend', 'confirmer',
    'confirm', 'supprimer', 'delete', 'voir tout', 'see all', 'tous les amis', 'all friends',
    'suggestions', 'demandes', 'requests', 'notifications', 'search', 'rechercher',
    'more', 'plus', 'menu', 'facebook',
})

# Texte typique des notifications / lignes secondaires (nombre d'amis communs, etc.).
_NOISE_RE = re.compile(
    r'(\d[\d\s.,]*\s+(?:mutual\s+friends?|friends?|amis?(?:\s+en\s+commun)?)\b'
    r'|mutual\s+friends?|amis?\s+en\s+commun|mentioned\s+you|vous\s+a\s+mentionn'
    r'|commented\s+on|a\s+comment[ée]|replied\s+to|a\s+r[ée]pondu|memories|souvenirs'
    r'|^unread|^non\s+lu|you\s+have\s|vous\s+avez\s|follow\s+a\s+few\s+steps)',
    re.IGNORECASE,
)


def normalise_space(text: str | None) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def is_valid_display_name(name: str | None, friend_id: str = '', forbidden_ids=None) -> bool:
    """Un nom d'ami valide : pas un libellé de navigation, pas une notification.

    La comparaison avec les libellés de navigation est EXACTE : Samia, Amina, Rami... passent.
    """
    cleaned = normalise_space(name)
    if not (2 <= len(cleaned) <= 100):
        return False
    lowered = cleaned.lower()
    if lowered in NAV_LABELS or _NOISE_RE.search(lowered) or re.fullmatch(r'[\d\s.,]+', cleaned):
        return False
    forbidden = set(DEFAULT_FORBIDDEN_IDS)
    forbidden.update(str(item).lower() for item in (forbidden_ids or ()))
    if friend_id and friend_id.lower() in forbidden:
        return False
    return True


# ------------------------------------------------------------------------ nombres

_NUMBER_RE = re.compile(
    r'(\d+(?:[\s\u00a0\u202f.,]\d{3})*(?:[.,]\d+)?)'
    r'(?:\s*(k|m|mille)(?![A-Za-zÀ-ÿ]))?',
    re.IGNORECASE,
)
_SPACES = re.compile(r'[\s\u00a0\u202f]')


def extract_leading_number(text: str | None) -> int:
    """'245' -> 245 ; '1 245' -> 1245 ; '1,2 k' -> 1200 ; '3 M' -> 3 000 000."""
    match = _NUMBER_RE.search(text or '')
    if not match:
        return 0
    raw, suffix = match.group(1), (match.group(2) or '').lower()
    try:
        if suffix:
            value = float(_SPACES.sub('', raw).replace(',', '.'))
            return int(round(value * (1_000_000 if suffix == 'm' else 1000)))
        return int(re.sub(r'[\s\u00a0\u202f.,]', '', raw))
    except ValueError:
        return 0


def normalise_reaction_label(label: str | None) -> str | None:
    value = (label or '').lower().replace('’', "'")
    if "j'aime" in value or 'jaime' in value or 'like' in value or 'me gusta' in value:
        return 'like'
    if 'adore' in value or 'love' in value or 'amour' in value or 'me encanta' in value:
        return 'love'
    if 'haha' in value or 'rire' in value or 'jaja' in value:
        return 'haha'
    if 'waouh' in value or 'wow' in value or 'ouah' in value:
        return 'wow'
    if 'triste' in value or 'sad' in value:
        return 'sad'
    if 'angry' in value or 'grrr' in value or 'colère' in value or 'enfadado' in value:
        return 'angry'
    if 'soutien' in value or 'care' in value:
        return 'care'
    return None


def strip_query(url: str | None) -> str:
    """URL sans paramètres (pour comparer deux URL d'image signées)."""
    return (url or '').split('?')[0]
