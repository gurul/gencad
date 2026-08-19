"""scan2cad: a screen-reader-native describe-and-draft tool.

Mesh in, plain-language geometry report plus an editable named-dimension
build123d script out. The scan is the draft; the caliper is the truth.

Only the frozen data model and the frozen thresholds are re-exported here, so
that importing `scan2cad` stays cheap and pulls in no heavy geometry
dependencies. Import the pipeline stages from their own modules.
"""

from __future__ import annotations

from scan2cad.primitives import CylinderFit, PlaneFit, SceneModel, SnapRecord

__all__ = ["CylinderFit", "PlaneFit", "SceneModel", "SnapRecord", "__version__"]

__version__ = "0.1.0"
