"""brain_meta.py - Batch 2: the Brain version LABEL. A label only: nothing in trading or in the Brain's decisions reads it.

BRAIN_VERSION is stamped on every new Dual trade and every Brain own trade at the moment it OPENS, so old history can always be told
apart from newer Brain logic. Old records have no label (they stay empty = "not recorded", never guessed or back-filled).
When Brain logic changes in a way that matters for comparing results, change the constant (b1 -> b2). Old rows keep their old label.
"""
BRAIN_VERSION = "b1"


def shown(v):
    """Text for a report: the label, or 'not recorded' for records made before versioning."""
    return str(v) if v else "not recorded"
