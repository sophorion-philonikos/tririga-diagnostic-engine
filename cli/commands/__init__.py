"""Command-handler package boundary.

Intent matching lives in ``cli/intents.py``. Handler implementations currently
reside in ``cli/router.py``; new handlers should land here and be wired from
the router to keep modules reviewable.
"""

# Map intent name -> owning module (documentation + future splits).
HANDLER_OWNERS = {
    'visualize': 'cli.router',
    'simulate': 'cli.simulation',
    'inventory': 'cli.inventory',
    'relations': 'cli.relations',
    'glossary': 'cli.knowledge',
}
