// Teste les snippets de browser/js.py sur du HTML simulé (jsdom). Lancé par test_js_snippets.py.
// Entrée (stdin) : {"snippets": {NOM: code}}  -  Sortie : [[nom_du_test, ok, détail], ...]
const path = require('path');
const jsdomPath = process.env.JSDOM_PATH || 'jsdom';
const { JSDOM } = require(jsdomPath);

let input = '';
process.stdin.on('data', d => input += d);
process.stdin.on('end', () => {
  const { snippets } = JSON.parse(input);
  const results = [];
  const check = (name, ok, detail) => results.push([name, !!ok, detail === undefined ? '' : String(detail)]);

  function page(html) {
    const dom = new JSDOM('<!doctype html><html><body>' + html + '</body></html>',
                          { url: 'https://www.facebook.com/', runScripts: 'outside-only' });
    const w = dom.window;
    const def = (proto, name, desc) => w.Object.defineProperty(proto, name, Object.assign({ configurable: true }, desc));
    function textOf(n) {
      if (n.nodeType === 3) return n.nodeValue;
      if (n.nodeType !== 1) return '';
      const tag = n.tagName.toLowerCase();
      if (tag === 'br') return '\n';
      let s = ''; for (const c of n.childNodes) s += textOf(c);
      return ['div', 'p', 'li', 'ul', 'section', 'article', 'h1', 'h2', 'h3'].includes(tag) ? '\n' + s + '\n' : s;
    }
    def(w.HTMLElement.prototype, 'innerText', { get() { return textOf(this).replace(/\n\s*\n+/g, '\n').replace(/^\s*\n+|\n+\s*$/g, ''); } });
    def(w.HTMLElement.prototype, 'offsetWidth', { get() { return 100; } });
    def(w.Element.prototype, 'scrollHeight', { get() { return +(this.getAttribute('data-sh') || 0); } });
    def(w.Element.prototype, 'clientHeight', { get() { return +(this.getAttribute('data-ch') || 0); } });
    def(w.Element.prototype, 'scrollTop', { get() { return this._st || 0; }, set(v) { this._st = v; } });
    w.Element.prototype.getBoundingClientRect = function () {
      return { width: +(this.getAttribute('data-w') || 0), height: +(this.getAttribute('data-h') || 0),
               top: +(this.getAttribute('data-top') || 0), left: 0 };
    };
    w.scrollBy = () => {};
    const run = (name, ...args) => w.eval('(function(){' + snippets[name] + '})').apply(null, args);
    return { w, d: w.document, run };
  }

  // ------------------------------------------------------------------ 1. liste d'amis
  {
    const row = (slug, name, mutual, img) =>
      `<div><a href="https://web.facebook.com/${slug}/"><img src="${img}"><div><span>${name}</span></div>` +
      (mutual ? `<div>${mutual}</div>` : '') + `</a><div role="button" aria-label="More">...</div></div>`;
    const html =
      `<div role="banner"><a href="https://web.facebook.com/notifications/">N</a>` +
      `<div role="dialog" aria-label="Notifications"><a href="https://web.facebook.com/permalink.php?story_fbid=1&notif_id=2&ref=notif">` +
      `<div>Unread Raïssa mentioned you</div></a></div></div>` +
      `<div role="navigation"><div>Friends</div><div>2,359 friends</div>` +
      `<div id="scroller" style="overflow-y:auto" data-sh="5000" data-ch="600">` +
      row('vero.hanitry', 'Vero Hanitry Ny Aina', '30 mutual friends', 'https://scontent.x/a.jpg') +
      row('profile.php?id=100099', "Dadan'i Branham", '', 'https://scontent.x/c.jpg') +
      row('samia.rakoto', 'Samia Rakoto', '5 mutual friends', 'https://scontent.x/s.jpg') +
      `</div></div>` +
      `<div role="main"><div>Select people's names to preview their profile.</div>` +
      `<a href="https://web.facebook.com/stories/1/x/?source=notification&notif_id=9">story</a></div>`;
    const p = page(html);
    const rows = p.run('JS_FRIEND_ANCHORS');
    const hrefs = Array.from(rows).map(r => r[0]);
    check('amis: liens de la cloche (banner/dialog/notif_id) exclus',
          !hrefs.some(h => /notifications|notif_id|stories/.test(h)), hrefs.join(' | '));
    const vero = Array.from(rows).find(r => r[0].includes('vero.hanitry'));
    check('amis: nom = première ligne du lien', vero && vero[1] === 'Vero Hanitry Ny Aina', vero && vero[1]);
    check('amis: photo de la ligne récupérée', vero && vero[3] === 'https://scontent.x/a.jpg', vero && vero[3]);
    check('amis: profile.php?id conservé dans le href', hrefs.some(h => h.includes('profile.php?id=100099')));
    check('amis: ligne sans amis communs gérée', Array.from(rows).some(r => r[1] === "Dadan'i Branham"));
    const hint = vero[0];
    const before = Array.from(p.run('JS_FRIEND_SCROLL', 0, hint));
    check('scroll amis: conteneur de liste détecté (pas la fenêtre)', before[0] === 'el' && before[2] === 5000, before.join(','));
    const after = Array.from(p.run('JS_FRIEND_SCROLL', 540, hint));
    check('scroll amis: scrollTop avance dans le conteneur', after[1] === 540, after.join(','));
    const total = p.run('JS_EXPECTED_TOTAL');
    check('amis: total annoncé lu', /2,359/.test(total), total);
    const badge = page('<div role="navigation"><span>1</span><div>Friends</div></div><div>1 friend request</div>');
    check('amis: badge « 1 » + libellé « Friends » à la ligne suivante n\'est PAS le total (bug : 1 ami annoncé)', badge.run('JS_EXPECTED_TOTAL') === '', badge.run('JS_EXPECTED_TOTAL'));
    const fr = page('<div>Amis</div><div>1\u202f204 amis</div><div>3 amis en commun</div>');
    check('amis: total en français avec espace fine insécable', /1.204/.test(fr.run('JS_EXPECTED_TOTAL')), fr.run('JS_EXPECTED_TOTAL'));
    const p2 = page('<div>5 amis en commun</div>');
    check('amis: "N amis en commun" n\'est pas pris pour le total', p2.run('JS_EXPECTED_TOTAL') === '');
    const none = Array.from(page('<div>rien</div>').run('JS_FRIEND_SCROLL', 0, ''));
    check('scroll amis: repli sur la fenêtre sans conteneur', none[0] === 'win', none.join(','));
  }

  // ------------------------------------------------------------------ 2. posts
  {
    const html =
      `<div role="main"><div role="article" aria-label="Publication"><div data-ad-preview="message">Mon premier post assez long pour être retenu.</div>` +
      `<a href="https://www.facebook.com/jean.dupont/posts/pfbid02abc?__cft__=1"><span>3 h</span></a>` +
      `<abbr title="12 octobre 2026">hier</abbr>` +
      `<div role="article" aria-label="Commentaire de Alice"><a role="link" href="/alice">Alice</a><div dir="auto">Commentaire imbriqué beaucoup plus long que le post lui-même, vraiment</div></div></div>` +
      `<div role="article"><div dir="auto">Un deuxième post sans lien permanent mais avec du texte suffisamment long pour passer le filtre.</div></div>` +
      `<div role="article"><div dir="auto">court</div></div></div>`;
    const p = page(html);
    const posts = Array.from(p.run('JS_POSTS', ['commentaire de', 'comment by']));
    check('posts: 2 posts (commentaire imbriqué et post sans texte exclus)', posts.length === 2, posts.length);
    check('posts: texte du post = son message, pas le commentaire', posts[0][2].startsWith('Mon premier post'), posts[0][2]);
    check('posts: clé = permalien sans paramètres', posts[0][1] === 'https://www.facebook.com/jean.dupont/posts/pfbid02abc', posts[0][1]);
    check('posts: lien permanent renvoyé (pour ouvrir les commentaires)', posts[0][4] && posts[0][4].tagName === 'A');
    check('posts: date lue', posts[0][3] === '12 octobre 2026', posts[0][3]);
    check('posts: clé de repli (hash) quand pas de permalien', /^h-?\d+$/.test(posts[1][1]), posts[1][1]);
  }

  // ------------------------------------------------------------------ 2b. posts sans texte / repli
  {
    const html =
      `<div role="main">` +
      `<div role="article"><div data-ad-rendering-role="story_message"><span>Hi</span></div><a href="https://www.facebook.com/x/posts/pfbid0aa?__cft__=1"><span>2 h</span></a></div>` +
      `<div role="article"><a href="https://www.facebook.com/x/photos/a.1/222/?type=3"><span>5 h</span></a><img src="https://scontent.x/p.jpg" data-w="500" data-h="400"></div>` +
      `<div role="article"><div role="button">J'aime</div></div>` +
      `</div>`;
    const p = page(html);
    const posts = Array.from(p.run('JS_POSTS', ['commentaire de', 'comment by']));
    check('posts: légende très courte (« Hi ») conservée via story_message', posts.length === 2 && posts[0][2] === 'Hi', posts.map(r => r[2]).join('|'));
    check('posts: photo sans texte conservée (clé = permalien)', posts[1] && posts[1][2] === '' && /photos/.test(posts[1][1]), posts[1] && posts[1][1]);
    check('posts: squelette vide ignoré', posts.length === 2, posts.length);
    const noRole =
      `<div role="main"><div id="card"><a href="https://www.facebook.com/x/posts/pfbid0bb"><span>1 j</span></a>` +
      `<div dir="auto">Un post dans une page sans role article, assez long.</div>` +
      `<div role="button" aria-label="J'aime">J'aime</div><div role="button" aria-label="Commenter">Commenter</div></div></div>`;
    const q = page(noRole);
    const fb = Array.from(q.run('JS_POSTS', ['commentaire de']));
    check('posts: repli par lien permanent quand aucun role=article', fb.length === 1 && fb[0][2].startsWith('Un post'), fb.length);
    const mixed =
      `<div role="main">` +
      `<div id="c1"><div data-ad-rendering-role="story_message"><span>Salama daholo</span></div>` +
      `<a href="https://www.facebook.com/x/posts/pfbid0cc"><span>3 h</span></a>` +
      `<div role="button" aria-label="J'aime">J'aime</div><div role="button" aria-label="Commenter">Commenter</div>` +
      `<div role="article" aria-label="Comment by Rivo 2 d"><a role="link" href="/rivo">Rivo</a><div dir="auto">Super</div></div></div>` +
      `<div id="c2"><div data-ad-rendering-role="story_message"><span>Deuxième publication ici</span></div>` +
      `<a href="https://www.facebook.com/x/posts/pfbid0dd"><span>1 j</span></a>` +
      `<div role="button" aria-label="Like">Like</div></div></div>`;
    const m = Array.from(page(mixed).run('JS_POSTS', ['commentaire de', 'comment by']));
    check('posts: articles = seulement des commentaires -> repli quand même utilisé (bug du log)', m.length === 2, m.length);
    check('posts: chaque carte garde son propre texte et permalien', m.length === 2 && m[0][2] === 'Salama daholo' && /pfbid0cc/.test(m[0][1]) && m[1][2].startsWith('Deuxième'), JSON.stringify(m.map(r => [r[1], r[2]])));
    const diag = page(html).run('JS_DIAG_POSTS');
    check('diagnostic: compteurs articles / permaliens', diag.articles === 3 && diag.permalinks >= 2, JSON.stringify([diag.articles, diag.permalinks]));
  }

  // ------------------------------------------------------------------ 2b'. réactions dans une carte sans role=article
  {
    const p = page(`<div id="card"><div role="button" aria-label="Like: 12 people" id="sum">12</div>` +
                   `<div role="article" aria-label="Comment by Rivo"><span role="button" aria-label="Like: 3 people" id="cm">3</span></div></div>`);
    const card = p.d.getElementById('card');
    const typ = 'j.aime|like|love', who = 'see who reacted';
    const b = p.run('JS_BOUTON_REACTIONS', card, ['commentaire'], typ, who);
    check('réactions: bouton trouvé dans une carte sans role=article (bug : 0 réaction)', b && b.id === 'sum', b && b.id);
    const l = Array.from(p.run('JS_LABELS_REACTIONS', card, ['commentaire'], typ));
    check('réactions: celles d\'un commentaire imbriqué sont exclues', l.length === 1, l.join('|'));
    const two = page(`<div id="c"><a href="https://www.facebook.com/autre.compte/posts/pfbid1">x</a>` +
                     `<a href="https://www.facebook.com/amie.x/posts/pfbid2">y</a>` +
                     `<div data-ad-rendering-role="story_message"><span>Message du post ici</span></div>` +
                     `<div role="button" aria-label="Like">Like</div></div>`);
    const rows = Array.from(two.run('JS_POSTS', ['comment by'], 'amie.x'));
    check('posts: le lien du propriétaire est préféré', rows.length === 1 && /amie\.x/.test(rows[0][4].href), rows[0] && rows[0][4] && rows[0][4].href);
  }

  // ------------------------------------------------------------------ 2c. bouton « N commentaires »
  {
    const p = page(`<div role="article" id="a"><div role="button" id="c">12 comments</div><div role="button">Comment</div></div>`);
    const art = p.d.getElementById('a');
    const re = '\\d[\\d.,\\s\\u00a0]*[kKmM]?\\s*(?:comments?|commentaires?)';
    const b = p.run('JS_BOUTON_COMMENTAIRES', art, re);
    check('commentaires: bouton « 12 comments » trouvé (pas « Comment » nu)', b && b.id === 'c');
    check('commentaires: aucun bouton -> null', p.run('JS_BOUTON_COMMENTAIRES', p.d.createElement('div'), re) === null);
  }

  // ------------------------------------------------------------------ 3. commentaires imbriqués
  {
    const html =
      `<div role="dialog"><div role="article" aria-label="Commentaire de Alice"><a role="link" href="/alice">Alice</a><div dir="auto">Salut</div>` +
      `<div role="article" aria-label="Réponse de Bob à un commentaire de Alice"><a role="link" href="/bob">Bob</a>` +
      `<div dir="auto">Ceci est une réponse beaucoup plus longue que le commentaire parent</div></div></div>` +
      `<div role="article" aria-label="Publication de Jean"><div dir="auto">Le post lui-même</div></div></div>`;
    const p = page(html);
    const dlg = p.d.querySelector('div[role="dialog"]');
    const rows = Array.from(p.run('JS_LIRE_COMMS', dlg, ['commentaire de', 'réponse de']));
    const alice = rows.find(r => r[0] === 'Alice'), bob = rows.find(r => r[0] === 'Bob');
    check('commentaires: 2 lus, le post lui-même exclu', rows.length === 2, rows.length);
    check('commentaires: texte du parent NON pollué par sa réponse (bug v1)', alice && alice[1] === 'Salut', alice && alice[1]);
    check('commentaires: la réponse est lue séparément', bob && bob[1].startsWith('Ceci est une réponse'), bob && bob[1]);
    const dlgs = Array.from(p.run('JS_DIALOGUES'));
    check('dialogues: visibles détectés', dlgs.length === 1);
  }

  // ------------------------------------------------------------------ 4. bouton "voir plus" (compteur)
  {
    const p = page(`<div role="dialog"><div role="button" id="b">Voir plus de commentaires</div><div role="button">J'aime</div></div>`);
    let clicks = 0; p.d.getElementById('b').addEventListener('click', () => clicks++);
    const dlg = p.d.querySelector('div[role="dialog"]');
    const re = 'voir\\s+plus|view\\s+more';
    const counts = [1, 2, 3, 4, 5].map(() => p.run('JS_EXPAND', dlg, re, 3).length);
    check('expansion: un même bouton est proposé 3 fois max (pas à l\'infini)', counts.join() === '1,1,1,0,0', counts.join());
    check('expansion: le JS ne clique JAMAIS lui-même (clic Selenium côté Python)', clicks === 0, clicks);
    const many = page(`<div role="dialog">${'<div role="button">Voir plus</div>'.repeat(5)}</div>`);
    check('expansion: au plus N boutons par passe', many.run('JS_EXPAND', many.d.querySelector('div[role="dialog"]'), re, 2).length === 2);
  }

  // ------------------------------------------------------------------ 5. réactions
  {
    const html =
      `<div role="article"><div role="button" aria-label="J'aime">J'aime</div>` +
      `<div role="button" aria-label="Commenter 3 commentaires">3</div>` +
      `<span role="button" aria-label="J'aime : 12 personnes" id="sum">12</span></div>`;
    const p = page(html);
    const art = p.d.querySelector('div[role="article"]');
    const typ = "j.aime|like|love|adore", who = 'voir qui a réagi|see who reacted';
    const btn = p.run('JS_BOUTON_REACTIONS', art, ['commentaire', 'comment'], typ, who);
    check('réactions: bouton = résumé chiffré (pas "J\'aime" nu ni "Commenter")', btn && btn.id === 'sum', btn && btn.getAttribute('aria-label'));
    const labels = Array.from(p.run('JS_LABELS_REACTIONS', art, ['commentaire', 'comment'], typ));
    check('réactions: repli par aria-label', labels.length === 1 && labels[0].includes('12'), labels.join('|'));
    const p2 = page(`<div role="dialog"><div role="tab" aria-label="Tous, 245">x</div><div role="tab">J'aime 200</div></div>`);
    const tabs = Array.from(p2.run('JS_ONGLETS', p2.d.querySelector('div[role="dialog"]')));
    check('réactions: onglets lus', tabs.join('|') === 'Tous, 245|J\'aime 200', tabs.join('|'));
  }

  // ------------------------------------------------------------------ 6. infos du profil
  {
    const own = 'https://scontent.x/own.jpg';
    const html =
      `<div role="banner"><img src="${own}?oh=1" data-w="40" data-h="40" data-top="5"></div>` +
      `<div role="main">` +
      `<img src="https://scontent.x/cover.jpg" data-w="820" data-h="312" data-top="60">` +
      `<img src="${own}?oh=2" data-w="170" data-h="170" data-top="200">` +
      `<img src="https://scontent.x/ami.jpg?oh=3" data-w="168" data-h="170" data-top="210">` +
      `<span dir="auto">Habite à Antananarivo</span><span dir="auto">Bonjour tout le monde</span>` +
      `<div>Rejoint Facebook en mars 2018</div>` +
      `<div role="article"><span dir="auto">Habite à Paris (texte d'un post)</span>` +
      `<img src="https://scontent.x/post.jpg" data-w="170" data-h="170" data-top="300"></div></div>`;
    const p = page(html);
    const bio = 'Habite|Travaille|Lives in', joined = '(?:Rejoint|Joined) Facebook[^\\n]*', gone = "Ce contenu n.est pas disponible";
    const info = p.run('JS_PROFILE_INFOS', bio, joined, gone, own);
    check('profil: photo = avatar de l\'ami (ni bandeau, ni couverture, ni MA photo)', info.photo === 'https://scontent.x/ami.jpg?oh=3', info.photo);
    check('profil: bio sans le texte des posts', info.bio === 'Habite à Antananarivo', info.bio);
    check('profil: date « Rejoint Facebook » trouvée', /mars 2018/.test(info.date), info.date);
    check('profil: pas "indisponible"', info.gone === false);
    const p2 = page(`<div role="main"><div>Ce contenu n'est pas disponible pour le moment</div></div>`);
    check('profil: page indisponible détectée', p2.run('JS_PROFILE_INFOS', bio, joined, gone, '').gone === true);
    check('session: photo du compte connecté lue dans le bandeau', p.run('JS_OWN_PHOTO').startsWith(own));
  }

  // ------------------------------------------------------------------ 6b. personnes ayant réagi
  {
    const html =
      `<div role="dialog"><div role="tablist"><a href="https://www.facebook.com/tabs/1">Onglet</a>` +
      `<div role="tab" aria-selected="true">Tous 12</div><div role="tab" aria-selected="false" id="t1">J'aime 8</div></div>` +
      `<div id="list"><a href="https://web.facebook.com/personne.1/"><span>Personne Un</span><div>3 mutual friends</div></a>` +
      `<a href="https://web.facebook.com/personne.2/" aria-label="Personne Deux"></a>` +
      `<a href="https://web.facebook.com/permalink.php?notif_id=1">notif</a></div></div>`;
    const p = page(html);
    const dlg = p.d.querySelector('div[role="dialog"]');
    const rows = Array.from(p.run('JS_REACTOR_ROWS', dlg));
    check('réacteurs: onglets et liens de notification exclus', rows.length === 2, rows.map(r => r[0]).join(' | '));
    check('réacteurs: nom = 1ère ligne, aria-label gardé', rows[0][1] === 'Personne Un' && rows[1][2] === 'Personne Deux', JSON.stringify(rows));
    let clicked = 0; p.d.getElementById('t1').addEventListener('click', () => clicked++);
    const tab = p.run('JS_CLICK_TAB', dlg, 1);
    check('onglet: renvoie l\'onglet demandé sans cliquer', tab && tab.id === 't1' && clicked === 0, clicked);
    check('onglet: index inexistant -> null', p.run('JS_CLICK_TAB', dlg, 9) === null);
    check('onglet: aria-selected lu', p.run('JS_TAB_SELECTED', dlg, 0) === true && p.run('JS_TAB_SELECTED', dlg, 1) === false);
    const p2 = page('<div role="dialog"><div role="tab">A</div></div>');
    check('onglet: sans aria-selected -> null', p2.run('JS_TAB_SELECTED', p2.d.querySelector('div[role="dialog"]'), 0) === null);
  }

  // ------------------------------------------------------------------ 6c. boutons à cliquer (renvoyés, jamais cliqués)
  {
    const p = page(`<div role="dialog"><div role="button" id="sort">Plus pertinents</div>` +
                   `<div role="button" id="other">Répondre</div><span aria-label="Fermer" id="x">x</span></div>` +
                   `<div role="menuitem" id="all">Tous les commentaires</div><div role="menuitem">Plus récents</div>`);
    let clicks = 0; for (const id of ['sort', 'all', 'x']) p.d.getElementById(id).addEventListener('click', () => clicks++);
    const dlg = p.d.querySelector('div[role="dialog"]');
    const sort = p.run('JS_TRI_PERTINENTS', dlg, 'plus\\s+pertinents?|most\\s+relevant');
    check('tri: renvoie le bouton « Plus pertinents »', sort && sort.id === 'sort');
    const all = p.run('JS_TRI_TOUS', 'tous\\s+les\\s+commentaires|all\\s+comments');
    check('tri: renvoie l\'option « Tous les commentaires »', all && all.id === 'all');
    check('tri: aucun résultat quand le bouton est absent', page('<div role="dialog"></div>').run('JS_TRI_PERTINENTS', null, 'xyz') === null);
    const close = Array.from(p.run('JS_FERMER'));
    check('fermeture: renvoie le bouton Fermer des fenêtres visibles', close.length === 1 && close[0].id === 'x');
    check('boutons: le JS ne clique jamais lui-même', clicks === 0, clicks);
  }

  // ------------------------------------------------------------------ 7. blocage
  {
    check('blocage: formulaire de connexion détecté', page('<input name="pass" type="password">').run('JS_BLOCK_CHECK').login === true);
    check('blocage: message de limitation détecté', page('<div>You\'re temporarily blocked</div>').run('JS_BLOCK_CHECK').blocked === true);
    const ok = page('<div role="main">Fil d\'actualité</div>').run('JS_BLOCK_CHECK');
    check('blocage: page normale = rien à signaler', !ok.login && !ok.blocked);
  }

  console.log(JSON.stringify(results));
});
