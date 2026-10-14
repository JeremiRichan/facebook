"""Nettoyage des CSV : retire les faux amis (notifications, routes) et les échecs enregistrés.

Les premières versions ont écrit comme « amis » des liens de notifications (permalink.php,
onthisday, professional_dashboard...) et ont enregistré des échecs réseau comme des profils à
0 post. Cet outil purge ces lignes de TOUS les fichiers, avec sauvegarde .bak-<date>.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Set

import pandas as pd

from ..config.settings import Paths
from ..core.text_utils import is_valid_stored_id


@dataclass
class CleanReport:
    bad_ids: Set[str] = field(default_factory=set)
    removed: Dict[str, int] = field(default_factory=dict)
    backups: List[Path] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines = [f'{len(self.bad_ids)} identifiants à retirer']
        lines += [f'  {name}: {count} ligne(s) retirée(s)' for name, count in self.removed.items()]
        lines += [f'  ATTENTION {message}' for message in self.skipped]
        return lines


def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _rewrite(path: Path, frame: pd.DataFrame, keep_mask: pd.Series, report: CleanReport,
             dry_run: bool, stamp: str) -> None:
    removed = int((~keep_mask).sum())
    report.removed[path.name] = removed
    if removed and not dry_run:
        backup = path.with_name(f'{path.name}.bak-{stamp}')
        shutil.copy2(path, backup)
        report.backups.append(backup)
        frame[keep_mask].to_csv(path, index=False, encoding='utf-8')


def clean_invalid_data(paths: Paths, retry_zero_posts: bool = False,
                       dry_run: bool = False) -> CleanReport:
    report = CleanReport()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')

    users = _read(paths.users_csv)
    if users is not None and 'id' in users.columns:
        invalid = ~users['id'].map(is_valid_stored_id)
        report.bad_ids = set(users.loc[invalid, 'id'])
        if retry_zero_posts and 'signaux' in users.columns:
            zero = users['signaux'].str.contains('zero_post', na=False) & (users['id'] != '__moi__')
            report.bad_ids |= set(users.loc[zero, 'id'])
        duplicated = users['id'].duplicated(keep='last') & (users['id'] != '__moi__')
        keep = ~users['id'].isin(report.bad_ids) & ~duplicated
        _rewrite(paths.users_csv, users, keep, report, dry_run, stamp)

    bad = report.bad_ids
    removed_post_ids: Set[str] = set()

    def process(path: Path, column: str, extra: Callable[[pd.DataFrame], pd.Series] | None = None,
                collect_posts: bool = False) -> None:
        try:
            frame = _read(path)
        except Exception as error:   # fichier malformé : on ne le réécrit surtout pas
            report.skipped.append(f'{path.name} illisible ({error}) : ignoré')
            return
        if frame is None or column not in frame.columns:
            return
        drop = frame[column].isin(bad)
        if extra is not None:
            drop = drop | extra(frame)
        if collect_posts and 'id_post' in frame.columns:
            removed_post_ids.update(frame.loc[drop, 'id_post'])
        _rewrite(path, frame, ~drop, report, dry_run, stamp)

    process(paths.posts_csv, 'id_auteur', collect_posts=True)
    process(paths.reactions_csv, 'id_post', lambda f: f['id_post'].isin(removed_post_ids))
    process(paths.reactors_csv, 'id_post', lambda f: f['id_post'].isin(removed_post_ids))
    process(paths.comments_csv, 'id_proprietaire',
            lambda f: f['id_post'].isin(removed_post_ids) if 'id_post' in f.columns
            else pd.Series(False, index=f.index))
    process(paths.photos_csv, 'id_owner')
    process(paths.relations_csv, 'cible')
    process(paths.progress_csv, 'id_traite',
            lambda f: ~f['id_traite'].map(is_valid_stored_id))
    return report
