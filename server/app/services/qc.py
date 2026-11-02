"""Shared quality-control thresholds (single source of truth)."""

# Landsat C2 L2 surface temperature over coastal Mumbai at the ~10:30 IST overpass
# is physically ≥ ~22 °C even over water in the post-monsoon/dry seasons. Values below
# this threshold are residual cloud / cloud-edge contamination. They are hidden in the
# visualisation and excluded from cell statistics; a clicked raw pixel is still
# returned, with a QC flag, never silently altered.
LST_QC_MIN_C = 20.0
