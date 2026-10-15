"""Allow ``python -m pyommyssh``."""

import sys

from pyommyssh.app import main

if __name__ == "__main__":
    sys.exit(main())
