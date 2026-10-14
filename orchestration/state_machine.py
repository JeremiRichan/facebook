"""Machine à états simple pour suivre (et journaliser) l'exécution du scraping."""

from __future__ import annotations

from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


class RunState(Enum):
    INITIAL = auto()
    BROWSER_READY = auto()
    FRIENDS_EXTRACTED = auto()
    PROFILING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    BLOCKED = auto()
    FAILED = auto()


TERMINAL_STATES = (RunState.COMPLETED, RunState.FAILED, RunState.BLOCKED, RunState.PAUSED)


class StateManager:
    def __init__(self, logger=None) -> None:
        self.current_state = RunState.INITIAL
        self.metadata: Dict[str, str] = {}
        self.history: List[Tuple[RunState, str]] = [(RunState.INITIAL, '')]
        self._logger = logger

    def transition(self, new_state: RunState, reason: str = '') -> None:
        # PROFILING se répète à chaque ami : on ne l'inscrit pas 2 000 fois dans l'historique.
        if new_state is not self.current_state:
            self.history.append((new_state, reason))
            if self._logger and new_state is not RunState.PROFILING:
                self._logger.debug('état : %s -> %s %s', self.current_state.name,
                                   new_state.name, reason)
        self.current_state = new_state
        if reason:
            self.metadata['last_reason'] = reason

    def is_terminal(self) -> bool:
        return self.current_state in TERMINAL_STATES

    def last_reason(self) -> Optional[str]:
        return self.metadata.get('last_reason')
