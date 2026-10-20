"""Constants of the FamilyOS integration."""

from datetime import timedelta
from logging import Logger, getLogger

DOMAIN = "familyos"
LOGGER: Logger = getLogger(__package__)

CONF_ACT_FOR = "act_for"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 3600

# How far ahead the calendar entity looks for "the next event".
EVENT_WINDOW = timedelta(days=60)

# The features of a family this integration can use. A feature is available when FamilyOS has the
# extension switched on and the app's role may read it.
FEATURE_CALENDAR = "calendar"
FEATURE_SHOPPING = "shopping"
FEATURE_TASKS = "tasks"
FEATURE_CHORES = "chores"
FEATURE_BOARD = "board"
FEATURE_DRAFTS = "drafts"
