"""PyInstaller entry point."""
import multiprocessing

from qrksdock.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
