"""What-If simulation package.

Public API stays ``from cli import simulation`` / ``simulation.run_simulation``.
Internals are split for reviewability; behavior is unchanged.
"""

from cli.simulation.runner import *  # noqa: F401,F403

# Explicit re-exports commonly used by web/CLI.
from cli.simulation.runner import (  # noqa: E402
    run_simulation,
)
