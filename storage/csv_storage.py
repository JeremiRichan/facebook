"""Stockage CSV : ouverture, écriture par ami (atomique) et fermeture centralisées.

Le schéma des colonnes est IDENTIQUE à celui de la v1 : neo4j_loader.py et fix_post.py
continuent de fonctionner sans changement.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

from ..core.models import ScoreResult, ScrapeResult

CSV_HEADERS: Dict[str, List[str]] = {
    'users': ['id', 'nom', 'date_creation', 'bio', 'photo_url',
              'score_fake', 'verdict', 'signaux', 'extraction_date'],
    'relations': ['source', 'cible', 'type', 'date_relation'],
    'posts': ['id_post', 'id_auteur', 'texte', 'date_post',
              'reactions_count', 'comments_count', 'reactions_detail', 'extraction_date'],
    'comments': ['id_comm', 'id_post', 'id_proprietaire', 'texte',
                 'nom_auteur', 'date_comm', 'extraction_date'],
    'photos': ['id_photo', 'id_owner', 'url', 'type', 'extraction_date'],
    'reactions': ['id_reaction', 'id_post', 'type', 'count', 'extraction_date'],
    'reactors': ['id_post', 'id_reacteur', 'nom_reacteur', 'url_reacteur', 'type',
                 'extraction_date'],
}


class CsvTable:
    """Un fichier CSV ouvert en ajout (en-tête écrit seulement si le fichier est vide)."""

    def __init__(self, path: Path, header: List[str]):
        self.path = path
        self.header = header
        self._file = open(path, 'a', newline='', encoding='utf-8')
        self.writer = csv.writer(self._file)
        if path.stat().st_size == 0:
            self.writer.writerow(header)
            self._file.flush()

    def write_rows(self, rows) -> None:
        self.writer.writerows(rows)

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass


Tables = Dict[str, CsvTable]


def open_all_tables(paths_by_key: Dict[str, Path]) -> Tables:
    return {key: CsvTable(path, CSV_HEADERS[key]) for key, path in paths_by_key.items()}


def close_all_tables(tables: Tables) -> None:
    for table in tables.values():
        table.close()


def flush_all(tables: Tables) -> None:
    for table in tables.values():
        table.flush()


def ensure_pivot_row(tables: Tables, now_iso: str) -> None:
    """Ajoute la ligne du compte pivot « __moi__ » si elle n'existe pas encore."""
    users = tables['users']
    users.flush()
    try:
        with open(users.path, newline='', encoding='utf-8') as handle:
            if any(row and row[0] == '__moi__' for row in csv.reader(handle)):
                return
    except OSError:
        pass
    users.write_rows([['__moi__', 'Moi', 'Inconnue', '', '', 0.0, 'REEL', 'compte_pivot', now_iso]])
    users.flush()


def write_scrape_result(tables: Tables, result: ScrapeResult, score: ScoreResult) -> None:
    """Écrit TOUT ce qui concerne un ami d'un bloc, puis vide les tampons.

    Appelé uniquement pour un résultat OK/UNAVAILABLE : un échec n'écrit jamais rien.
    """
    profile = result.profile
    tables['posts'].write_rows(
        [post.post_id, post.owner_id, post.text_content, post.date_text, post.reactions_total,
         post.comments_total, json.dumps(post.reactions_detail, ensure_ascii=False),
         post.extracted_at] for post in result.posts)
    tables['reactions'].write_rows(
        [r.reaction_id, r.post_id, r.reaction_type, r.count, r.extracted_at]
        for r in result.reactions)
    if 'reactors' in tables:
        tables['reactors'].write_rows(
            [r.post_id, r.reactor_id, r.reactor_name, r.reactor_url, r.reaction_type,
             r.extracted_at] for r in result.reactors)
    tables['comments'].write_rows(
        [c.comment_id, c.post_id, c.owner_id, c.text_content, c.author_name, c.date_text,
         c.extracted_at] for c in result.comments)
    tables['photos'].write_rows(
        [p['photo_id'], p['owner_id'], p['url'], p['photo_type'], profile.extracted_at]
        for p in result.photos)
    tables['relations'].write_rows(
        [['__moi__', profile.friend_id, 'MON_AMI', profile.extracted_at]])
    # La ligne « users » est écrite EN DERNIER : si on plante avant, l'ami n'est pas considéré
    # comme traité à la reprise.
    tables['users'].write_rows(
        [[profile.friend_id, profile.display_name, profile.account_created, profile.bio,
          profile.photo_url, score.score_fake, score.verdict, score.signals,
          profile.extracted_at]])
    flush_all(tables)
