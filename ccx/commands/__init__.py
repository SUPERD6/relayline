"""ccx commands, one module per group; each has register(sub) for its parser part."""
from . import ability, autonomy, board, delegation, discuss, install, intake, memory, projects, records, ui, ways, workqueue

MODULES = (delegation, memory, install, records, workqueue, ui, discuss, ways, board, projects, autonomy, intake, ability)
