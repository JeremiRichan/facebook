"""Snippets JavaScript exécutés via driver.execute_script.

Pourquoi du JS ? Chaque appel Selenium (find_elements, .text, get_attribute) est un aller-retour
HTTP vers chromedriver (~10-50 ms). Extraire 170 liens un par un prenait ~45 s ; un snippet qui
fait tout le travail côté navigateur renvoie le même résultat en un seul appel.

Chaque snippet est le CORPS d'une fonction : il lit `arguments[...]` et se termine par `return`.
"""

# ---------------------------------------------------------------------------- amis

# Liens candidats de la page « Tous les amis ». On exclut la barre du haut (notifications,
# menu de compte) et les fenêtres modales ; le filtrage fin se fait côté Python.
JS_FRIEND_ANCHORS = r"""
function rowImage(a) {
  let el = a;
  for (let i = 0; i < 5 && el; i++, el = el.parentElement) {
    const imgs = el.querySelectorAll('img, image');
    if (imgs.length) {
      const hrefs = new Set(Array.from(el.querySelectorAll('a[href]')).map(x => x.href));
      return hrefs.size <= 3 ? imgs[0] : null;   // on reste à l'échelle d'UNE ligne d'ami
    }
  }
  return null;
}
const out = [];
for (const a of document.querySelectorAll('a[href]')) {
  if (a.closest('[role="banner"],[role="dialog"],[aria-label="Notifications"],[aria-label="Notification"]')) continue;
  const href = a.href || '';
  if (/notif_id|notif_t|[?&]ref=notif/i.test(href)) continue;
  const lines = (a.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  const im = rowImage(a);
  const src = im ? (im.src || im.getAttribute('xlink:href') || im.getAttribute('href') || '') : '';
  out.push([href, lines[0] || '', a.getAttribute('aria-label') || '', src]);
}
return out;
"""

# Fait défiler le conteneur de la LISTE (colonne de gauche, avec son propre ascenseur) et pas la
# fenêtre. arguments[0] = pixels à défiler (0 = juste mesurer), arguments[1] = href d'un ami connu
# (sert à retrouver le conteneur). Retourne [type, position, hauteur_totale, hauteur_visible].
JS_FRIEND_SCROLL = r"""
const delta = arguments[0], hint = arguments[1];
function scrollable(el) {
  const s = getComputedStyle(el);
  return /(auto|scroll|overlay)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 20;
}
let sc = window.__scFriendScroller;
if (!sc || !document.contains(sc)) {
  sc = null;
  if (hint) {
    const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === hint);
    let el = a ? a.parentElement : null;
    while (el && el !== document.body && el !== document.documentElement) {
      if (scrollable(el)) { sc = el; break; }
      el = el.parentElement;
    }
  }
  window.__scFriendScroller = sc;
}
if (sc) {
  if (delta) sc.scrollTop += delta;
  return ['el', sc.scrollTop, sc.scrollHeight, sc.clientHeight];
}
if (delta) window.scrollBy(0, delta);
const h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
return ['win', window.scrollY, h, window.innerHeight];
"""

# Nombre total d'amis affiché par Facebook (« 2,359 friends ») : sert à vérifier la complétude.
JS_EXPECTED_TOTAL = r"""
// Le nombre et le mot doivent être sur la MÊME ligne : un badge « 1 » suivi du libellé « Friends »
// à la ligne suivante (menu, demandes d'amis) n'est pas le total.
const t = document.body ? (document.body.innerText || '') : '';
const re = /(\d[\d.,\u00a0\u202f]*)[ \u00a0\u202f]+(?:friends|amis)\b(?![ \u00a0]+(?:en\s+commun|in\s+common))/ig;
let best = '', m;
while ((m = re.exec(t)) !== null) {
  const digits = parseInt(m[1].replace(/\D/g, ''), 10);
  if (digits > (parseInt(best.replace(/\D/g, ''), 10) || 0)) best = m[1];
}
return best.trim();
"""

# Photo du compte connecté (barre du haut) : à ne JAMAIS confondre avec celle d'un ami.
JS_OWN_PHOTO = r"""
const b = document.querySelector('[role="banner"]');
if (!b) return '';
for (const im of b.querySelectorAll('img, image')) {
  const src = im.src || im.getAttribute('xlink:href') || im.getAttribute('href') || '';
  if (/scontent|fbcdn/.test(src)) return src;
}
return '';
"""

# Aide au diagnostic : décrit les 80 premiers liens et leurs conteneurs.
JS_DIAG_ANCHORS = r"""
function chain(el) {
  const parts = [];
  for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
    let s = el.tagName.toLowerCase();
    if (el.getAttribute('role')) s += '[role=' + el.getAttribute('role') + ']';
    if (el.getAttribute('aria-label')) s += '[aria=' + el.getAttribute('aria-label').slice(0, 30) + ']';
    parts.push(s);
  }
  return parts.join(' < ');
}
const out = [];
for (const a of Array.from(document.querySelectorAll('a[href]')).slice(0, 80)) {
  out.push({
    href: a.href, text: (a.innerText || '').trim().slice(0, 80),
    aria: a.getAttribute('aria-label') || '', chain: chain(a.parentElement),
  });
}
return out;
"""

# ------------------------------------------------------------------------ session

# arguments[0] = {login: bool, blocked: bool}
JS_BLOCK_CHECK = r"""
const txt = (document.body ? (document.body.innerText || '') : '').slice(0, 4000);
return {
  login: !!document.querySelector('input[name="pass"]'),
  blocked: /temporarily blocked|temporairement bloqu|we limit how often|nous limitons|suspicious activity|activité inhabituelle|confirm your identity|confirmez votre identité/i.test(txt),
};
"""

JS_DIALOGUES = r"""
return Array.from(document.querySelectorAll('div[role="dialog"]')).filter(d => d.offsetWidth > 0);
"""

JS_FERMER = r"""
const out = [];
for (const d of document.querySelectorAll('div[role="dialog"]')) {
  if (!d.offsetWidth) continue;
  const b = d.querySelector('[aria-label="Fermer"],[aria-label="Close"],[aria-label="Close dialog"],' +
                            '[aria-label="Fermer la boîte de dialogue"],[aria-label="Cerrar"],[aria-label="Schließen"]');
  if (b) out.push(b);
}
return out;
"""

# ------------------------------------------------------------------------ profil

# arguments : [0]=regex bio, [1]=regex "a rejoint Facebook", [2]=regex "indisponible",
#             [3]=URL (sans paramètres) de la photo du compte connecté, à ignorer.
JS_PROFILE_INFOS = r"""
const reBio = new RegExp(arguments[0], 'i');
const reJoined = new RegExp(arguments[1], 'i');
const reGone = new RegExp(arguments[2], 'i');
const ownPhoto = arguments[3] || '';
const root = document.querySelector('div[role="main"]') || document.body;
const parts = [];
function add(t, max) {
  t = (t || '').trim();
  if (t.length >= 3 && t.length <= max && parts.indexOf(t) < 0) parts.push(t);
}
for (const el of document.querySelectorAll('[aria-label*="Intro"],[aria-label*="Présentation"],[data-testid="intro_bio"]')) {
  if (el.closest('div[role="article"]') || el.closest('[role="banner"]')) continue;
  add(el.innerText, 500);
}
for (const s of root.querySelectorAll('span[dir="auto"]')) {
  if (s.closest('div[role="article"]')) continue;
  const t = (s.innerText || '').trim();
  if (t.indexOf('\n') < 0 && reBio.test(t)) add(t, 200);
}
const corps = document.body ? (document.body.innerText || '') : '';
const joined = corps.match(reJoined);
let photo = '';
for (const im of root.querySelectorAll('img, image')) {
  const src = im.src || im.getAttribute('xlink:href') || im.getAttribute('href') || '';
  if (!/scontent|fbcdn/.test(src)) continue;
  if (ownPhoto && src.split('?')[0] === ownPhoto) continue;
  if (im.closest('div[role="article"]') || im.closest('[role="banner"]')) continue;
  const r = im.getBoundingClientRect();
  if (r.width >= 100 && r.width <= 400 && Math.abs(r.width - r.height) <= r.width * 0.1 && r.top < 700) {
    photo = src; break;
  }
}
return {
  bio: parts.slice(0, 8).join(' | '),
  date: joined ? joined[0] : '',
  photo: photo,
  gone: reGone.test(corps),
};
"""

# Posts visibles : [element, clé, texte, date, lien_permalien]. arguments[0] = préfixes des
# aria-label de commentaires (pour ne pas confondre commentaire et post).
#
# Un post n'a PAS forcément de texte (photo seule, reel, partage) : on le garde dès qu'il a un
# lien permanent, un média ou un contenu non négligeable. Seuls les emplacements vides que
# Facebook met à la place des posts hors écran sont ignorés. Si la page n'expose aucun
# role="article", on reconstruit les posts à partir de leurs liens permanents.
JS_POSTS = r"""
const PREF = arguments[0];
const FID = String(arguments[1] || '').toLowerCase();
function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0; } return 'h' + h; }
const LINK_SELS = ['a[href*="/posts/"]', 'a[href*="story_fbid"]', 'a[href*="/permalink"]',
  'a[href*="pfbid"]', 'a[href*="/photos/"]', 'a[href*="/photo/"]', 'a[href*="/photo.php"]',
  'a[href*="/videos/"]', 'a[href*="/watch/"]', 'a[href*="/reel/"]', 'a[href*="/share/p/"]',
  'a[href*="/share/r/"]', 'a[href*="/share/v/"]', 'a[href*="fbid"]'];
const LINK_ANY = LINK_SELS.join(',');
const MSG_SELS = '[data-ad-rendering-role="story_message"],div[data-ad-preview="message"]';
const out = [];

function isComment(a) {
  const lab = (a.getAttribute('aria-label') || '').toLowerCase();
  return PREF.some(p => lab.includes(p));
}

function build(a, own) {
  let texte = '';
  const msg = Array.from(a.querySelectorAll(MSG_SELS)).filter(own)[0];
  if (msg) texte = (msg.innerText || '').trim();
  if (!texte) {
    for (const d of a.querySelectorAll('div[dir="auto"],span[dir="auto"]')) {
      if (!own(d)) continue;
      if (d.closest('a,[role="button"],[role="link"],h2,h3,h4,[role="tablist"],[data-ad-rendering-role="profile_name"]')) continue;
      const t = (d.innerText || '').trim();
      if (t.length >= 2 && (t.indexOf('\n') >= 0 || t.length > 12)) { texte = t; break; }
    }
  }
  let link = null, href = '';
  const cands = [];
  for (const sel of LINK_SELS) {
    for (const l of Array.from(a.querySelectorAll(sel)).filter(own)) {
      if (l.offsetWidth > 0 && !cands.includes(l)) cands.push(l);
    }
  }
  // on préfère un lien qui désigne le profil scrapé (jamais celui d'un autre compte)
  link = (FID && cands.find(l => (l.href || '').toLowerCase().includes(FID))) || cands[0] || null;
  if (link) href = link.href;
  const total = (a.innerText || '').trim();
  let media = false;
  for (const im of a.querySelectorAll('img, video')) {
    if (!own(im)) continue;
    const r = im.getBoundingClientRect();
    if (r.width >= 150 && r.height >= 100) { media = true; break; }
  }
  // Emplacement vide (post hors écran remplacé par un squelette) : rien à lire.
  if (!texte && !href && !media && total.length < 40) return null;
  let key = '';
  if (href) { const m = href.match(/(?:story_fbid|fbid)=(\w+)/); key = m ? 'f' + m[1] : href.split('?')[0]; }
  if (!key) key = hash((texte || total).slice(0, 300));
  let date = '';
  const dEl = Array.from(a.querySelectorAll('abbr,time,[data-utime]')).filter(own)[0];
  if (dEl) date = (dEl.getAttribute('title') || dEl.getAttribute('aria-label') ||
                   dEl.getAttribute('data-utime') || dEl.innerText || '').trim();
  if (!date && link) {
    const lt = (link.getAttribute('aria-label') || link.innerText || '').trim();
    if (lt && lt.length < 40) date = lt;
  }
  return [a, key, texte.slice(0, 1500), date, link];
}

const articles = Array.from(document.querySelectorAll('div[role="article"]'));
for (const a of articles) {
  if (isComment(a)) continue;
  if (a.parentElement && a.parentElement.closest('div[role="article"]')) continue;
  const row = build(a, el => el.closest('div[role="article"]') === a);
  if (row) out.push(row);
}

if (!out.length) {
  // Repli : les posts ne sont pas des role="article" (ceux-ci peuvent n'être que des commentaires).
  // On part des messages de post et des liens permanents, puis on remonte jusqu'à la « carte »
  // du post : le plus petit ancêtre qui contient la barre d'actions J'aime / Commenter / Partager.
  const seen = new Set();
  const ACTION = /j.aime|like|comment|réagi|react|partag|share/i;
  const seeds = Array.from(document.querySelectorAll(MSG_SELS + ',' + LINK_ANY));
  for (const l of seeds) {
    if (!l.offsetWidth) continue;
    if (l.closest('[role="banner"],[role="dialog"],[role="navigation"],[role="tablist"]')) continue;
    const parentArt = l.closest('div[role="article"]');
    if (parentArt && isComment(parentArt)) continue;
    let el = l.parentElement, card = null;
    for (let i = 0; i < 16 && el && el !== document.body; i++, el = el.parentElement) {
      if (el.querySelectorAll(MSG_SELS).length > 1) break;   // on a dépassé le post : plusieurs posts ici
      const acts = Array.from(el.querySelectorAll('[aria-label]')).filter(x => ACTION.test(x.getAttribute('aria-label') || ''));
      if (acts.length >= 1 && (el.innerText || '').length > 15) { card = el; break; }
    }
    if (!card || seen.has(card)) continue;
    if (card.closest('div[role="article"]') && isComment(card.closest('div[role="article"]'))) continue;
    seen.add(card);
    const row = build(card, el => !el.closest('div[role="article"]') || el.closest('div[role="article"]') === card);
    if (row) out.push(row);
  }
}
return out;
"""

# Instantané de diagnostic quand 0 post est lu : de quoi voir ce que Facebook affiche vraiment.
JS_DIAG_POSTS = r"""
const q = s => document.querySelectorAll(s).length;
const main = document.querySelector('div[role="main"]') || document.body;
const art = document.querySelector('div[role="article"]');
return {
  url: location.href,
  articles: q('div[role="article"]'),
  articles_labelled: q('div[role="article"][aria-label]'),
  feed_units: q('[data-pagelet*="FeedUnit"],[data-pagelet*="ProfileTimeline"],[aria-posinset]'),
  story_message: q('[data-ad-rendering-role="story_message"]'),
  old_message: q('div[data-ad-preview="message"]'),
  permalinks: q('a[href*="/posts/"],a[href*="pfbid"],a[href*="story_fbid"],a[href*="/permalink"],a[href*="/reel/"],a[href*="/videos/"],a[href*="/photo"]'),
  dialogs: q('div[role="dialog"]'),
  main_text: (main.innerText || '').slice(0, 1500),
  first_article_labels: Array.from(document.querySelectorAll('div[role="article"]')).slice(0, 8)
    .map(a => (a.getAttribute('aria-label') || '') + ' :: ' + (a.innerText || '').slice(0, 80).replace(/\n/g, ' / ')),
  first_article_html: art ? art.outerHTML.slice(0, 6000) : ''
};
"""

# ------------------------------------------------------------------------ réactions

# arguments : [0]=article, [1]=mots exclus, [2]=regex types de réaction, [3]=regex "voir qui a réagi"
JS_BOUTON_REACTIONS = r"""
const art = arguments[0];
const own = el => { const c = el.closest('div[role="article"]'); return c === art || (art.getAttribute('role') !== 'article' && !c); };
const excl = arguments[1].map(s => s.toLowerCase());
const typ = new RegExp(arguments[2], 'i');
const who = new RegExp(arguments[3], 'i');
for (const el of art.querySelectorAll('[aria-label]')) {
  if (!own(el)) continue;
  if (!el.offsetWidth) continue;
  const lab = el.getAttribute('aria-label') || '';
  const low = lab.toLowerCase();
  if (excl.some(x => low.includes(x))) continue;
  if (who.test(lab) || (/\d/.test(lab) && typ.test(lab))) return el;
}
return null;
"""

JS_LABELS_REACTIONS = r"""
const art = arguments[0];
const own = el => { const c = el.closest('div[role="article"]'); return c === art || (art.getAttribute('role') !== 'article' && !c); };
const excl = arguments[1].map(s => s.toLowerCase());
const typ = new RegExp(arguments[2], 'i');
const out = [];
for (const el of art.querySelectorAll('[aria-label]')) {
  if (!own(el)) continue;
  const lab = el.getAttribute('aria-label') || '';
  const low = lab.toLowerCase();
  if (!low || excl.some(x => low.includes(x))) continue;
  if (/\d/.test(lab) && typ.test(lab)) out.push(lab);
}
return out;
"""

JS_ONGLETS = r"""
return Array.from(arguments[0].querySelectorAll('[role="tab"]'))
  .map(t => (t.getAttribute('aria-label') || t.innerText || '').trim());
"""

# ----------------------------------------------------- personnes ayant réagi (option)

# arguments : [0]=fenêtre des réactions, [1]=index de l'onglet à ouvrir
JS_CLICK_TAB = r"""
const tabs = arguments[0].querySelectorAll('[role="tab"]');
const t = tabs[arguments[1]];
return t || null;
"""

# L'onglet est-il bien sélectionné ? (null = Facebook n'expose pas aria-selected)
JS_TAB_SELECTED = r"""
const t = arguments[0].querySelectorAll('[role="tab"]')[arguments[1]];
if (!t) return false;
const v = t.getAttribute('aria-selected');
return v === null ? null : v === 'true';
"""

# Lignes de personnes de la fenêtre : [href, première ligne de texte, aria-label].
# Les onglets (role=tablist) et les liens de notification sont ignorés.
JS_REACTOR_ROWS = r"""
const out = [];
for (const a of arguments[0].querySelectorAll('a[href]')) {
  if (a.closest('[role="tablist"]')) continue;
  const href = a.href || '';
  if (/notif_id|notif_t|[?&]ref=notif/i.test(href)) continue;
  const lines = (a.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  out.push([href, lines[0] || '', a.getAttribute('aria-label') || '']);
}
return out;
"""

# ---------------------------------------------------------------------- commentaires

# Post sans lien permanent exploitable : on ouvre sa fenêtre en cliquant « 12 commentaires ».
# arguments : [0]=article, [1]=regex du compteur de commentaires. Renvoie l'élément (sans cliquer).
JS_BOUTON_COMMENTAIRES = r"""
const art = arguments[0];
const own = el => { const c = el.closest('div[role="article"]'); return c === art || (art.getAttribute('role') !== 'article' && !c); };
const re = new RegExp(arguments[1], 'i');
for (const el of art.querySelectorAll('[role="button"],a[role="link"],a[role="button"],span[role="button"]')) {
  if (!own(el)) continue;
  if (!el.offsetWidth) continue;
  const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim();
  if (t && t.length < 80 && re.test(t)) return el;
}
return null;
"""

# arguments : [0]=racine (dialogue ou null), [1]=regex du bouton de tri
JS_TRI_PERTINENTS = r"""
const root = arguments[0] || document;
const re = new RegExp(arguments[1], 'i');
for (const b of root.querySelectorAll('div[role="button"]')) {
  const t = (b.innerText || '').trim();
  if (t && t.length < 60 && re.test(t)) return b;
}
return null;
"""

# arguments[0] = regex de l'option « Tous les commentaires »
JS_TRI_TOUS = r"""
const re = new RegExp(arguments[0], 'i');
for (const o of document.querySelectorAll('div[role="menuitem"],div[role="menuitemradio"]')) {
  if (re.test(o.innerText || '')) return o;
}
return null;
"""

# Renvoie (sans cliquer) jusqu'à arguments[2] boutons « Voir plus / N réponses » : Python les clique
# un par un avec Selenium (clic fiable) et un délai aléatoire. Un compteur par bouton évite de
# recliquer indéfiniment le même.
JS_EXPAND = r"""
const root = arguments[0] || document;
const re = new RegExp(arguments[1], 'i');
const max = arguments[2] || 3, out = [];
for (const b of root.querySelectorAll('div[role="button"],span[role="button"],a[role="button"]')) {
  if (out.length >= max) break;
  const c = parseInt(b.dataset.scN || '0');
  if (c >= 3) continue;
  const t = (b.innerText || '').trim();
  if (!t || t.length > 120 || !re.test(t)) continue;
  b.dataset.scN = String(c + 1);
  out.push(b);
}
return out;
"""

# Lit les commentaires : [auteur, texte, date, aria-label]. Le texte d'un commentaire exclut celui
# de ses réponses imbriquées (own()), contrairement à la v1 qui prenait le texte le plus long.
JS_LIRE_COMMS = r"""
const root = arguments[0] || document;
const pref = arguments[1];
const out = [];
for (const c of root.querySelectorAll('div[role="article"]')) {
  const aria = c.getAttribute('aria-label') || '';
  const lab = aria.toLowerCase();
  if (!pref.some(p => lab.includes(p))) continue;
  const own = el => el.closest('div[role="article"]') === c;
  let auteur = '';
  for (const a of c.querySelectorAll('a[role="link"]')) {
    if (!own(a)) continue;
    const t = (a.innerText || '').trim().split('\n')[0].trim();
    if (t.length > 1 && t.length < 80) { auteur = t; break; }
  }
  let texte = '';
  for (const d of c.querySelectorAll('div[dir="auto"]')) {
    if (!own(d)) continue;
    const t = (d.innerText || '').trim();
    if (t && t !== auteur && t.length > 1 && t.length < 2000 && t.length > texte.length) texte = t;
  }
  let date = '';
  for (const e of c.querySelectorAll('abbr,time,a[role="link"] span')) {
    if (!own(e)) continue;
    const d = (e.getAttribute('title') || e.getAttribute('aria-label') || e.innerText || '').trim();
    if (d && /\d/.test(d) && d.length < 60) { date = d; break; }
  }
  out.push([auteur, texte, date, aria]);
}
return out;
"""

JS_SCROLL_ZONE = r"""
const dlg = arguments[0];
if (!dlg) { window.scrollBy(0, 800); return document.body.scrollHeight; }
let best = null, bestH = 0;
for (const el of dlg.querySelectorAll('div')) {
  if (el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 150 && el.scrollHeight > bestH) {
    bestH = el.scrollHeight; best = el;
  }
}
if (best) { best.scrollTop = best.scrollHeight; return best.scrollHeight; }
window.scrollBy(0, 800);
return document.body.scrollHeight;
"""

# HTML (tronqué) d'une fenêtre : sert au diagnostic quand aucun réacteur n'est lu.
JS_DIALOG_HTML = r"""
const d = arguments[0];
return d ? {tabs: Array.from(d.querySelectorAll('[role="tab"]')).map(t => (t.innerText || t.getAttribute('aria-label') || '').trim()),
            links: d.querySelectorAll('a[href]').length,
            text: (d.innerText || '').slice(0, 1200),
            html: d.outerHTML.slice(0, 15000)} : null;
"""

ALL_SNIPPETS = {
    name: value for name, value in globals().items()
    if name.startswith('JS_') and isinstance(value, str)
}
