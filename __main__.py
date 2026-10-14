import os
import sys

# Permet `python3 __main__.py` depuis le dossier du paquet, en plus de `python -m fb_modular`.
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from fb_modular.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
