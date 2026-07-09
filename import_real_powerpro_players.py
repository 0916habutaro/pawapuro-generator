"""Compatibility entry point for the real PowerPro player importer."""

from scripts.import_real_powerpro_players import *  # noqa: F403
from scripts.import_real_powerpro_players import main


if __name__ == "__main__":
    raise SystemExit(main())
