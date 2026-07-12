"""Signal module: pattern rule evaluation post-write (FR-17 to FR-19, FR-21).

Rules run as a post-write hook after each resolution and on demand via an
admin endpoint. A fired rule creates a Signal node and hands it to the
emitter. Signals advise, humans decide (§5.3).
"""
