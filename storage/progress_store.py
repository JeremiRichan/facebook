"""Suivi de progression (reprise après interruption) et cache de la liste d'amis."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import List, Optional, Set

import pandas as pd


def _read_column(path: Path, column: str) -> List[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return []
    if column not in frame.columns:
        return []
    return [str(value).strip() for value in frame[column] if str(value).strip()]


def load_processed_ids(progress_csv: Path, users_csv: Path) -> Set[str]:
    """IDs déjà traités = fichier de progression + colonne id de Facebook_User.csv."""
    processed: Set[str] = set()
    for path, column in ((progress_csv, 'id_traite'), (users_csv, 'id')):
        for value in _read_column(path, column):
            if value != '__moi__':
                processed.add(value)
    return processed


def save_progress(progress_csv: Path, processed_id: str) -> None:
    is_new = not progress_csv.exists() or progress_csv.stat().st_size == 0
    with open(progress_csv, 'a', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(['id_traite'])
        writer.writerow([processed_id.strip()])


def is_already_processed(candidate_id: str, processed_ids: Set[str]) -> bool:
    return bool(candidate_id) and candidate_id in processed_ids


# ------------------------------------------------------------------- cache liste d'amis

def load_friends_cache(path: Path, max_age_hours: float) -> Optional[List[dict]]:
    """Liste d'amis en cache, ou None si absente / trop ancienne / illisible."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        friends = payload['friends']
        age_hours = (time.time() - float(payload['saved_at'])) / 3600
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not friends or age_hours > max_age_hours:
        return None
    return friends


def save_friends_cache(path: Path, friends: List[dict]) -> None:
    payload = {'saved_at': time.time(), 'count': len(friends), 'friends': friends}
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)             # remplacement atomique : jamais de cache à moitié écrit
