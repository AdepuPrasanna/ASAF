"""
ASAF backend - server-side risk prediction (Module 3).

Wraps the Random Forest trained in the ASAF_Risk_Model_Training notebook
(Section V-B, Table V: accuracy 0.862, macro F1 0.870).

IMPORTANT label ordering note: sklearn's LabelEncoder sorts class labels
alphabetically, so the trained model's output index order is:
    0 -> "high risk"
    1 -> "low risk"
    2 -> "mid risk"
This order is preserved here and must match the frontend's RISK_LABELS array.
"""

import os
import warnings
import joblib

# ---------------------------------------------------------------------
# Compatibility shim: this model file was saved with numpy>=2.0, which
# stores arrays under the "numpy._core" module path. Older numpy versions
# (numpy<2, e.g. the numpy bundled with Python 3.8 environments) don't have
# this module and raise "ModuleNotFoundError: No module named 'numpy._core'"
# when unpickling. This alias makes numpy._core resolve to numpy.core so the
# model can be loaded on either numpy major version.
# ---------------------------------------------------------------------
import sys
import numpy as _np
if not hasattr(_np, "_core"):
    import numpy.core as _np_core
    sys.modules.setdefault("numpy._core", _np_core)
    for _sub in ["multiarray", "numeric", "umath", "_multiarray_umath", "numerictypes", "fromnumeric", "_internal"]:
        if hasattr(_np_core, _sub):
            sys.modules.setdefault("numpy._core." + _sub, getattr(_np_core, _sub))

# The model may also have been trained with a newer scikit-learn version
# than is installed; sklearn warns about this but still loads correctly for
# the simple predict/predict_proba calls used here.
warnings.filterwarnings("ignore", message=".*Trying to unpickle estimator.*")
warnings.filterwarnings("ignore", message=".*does not have valid feature names.*")

FEATURE_ORDER = ["Age", "SystolicBP", "DiastolicBP", "BS", "BodyTemp", "HeartRate"]
RISK_LABELS = ["high risk", "low risk", "mid risk"]

# Mean feature values for the "low risk" class - healthy baseline used to
# explain which inputs are pushing a prediction toward higher risk.
LOW_RISK_MEANS = {
    "Age": 26.87, "SystolicBP": 105.87, "DiastolicBP": 72.53,
    "BS": 7.22, "BodyTemp": 98.37, "HeartRate": 72.77,
}
FEATURE_RANGE = {
    "Age": (10, 70), "SystolicBP": (70, 160), "DiastolicBP": (49, 100),
    "BS": (6, 19), "BodyTemp": (98, 103), "HeartRate": (7, 90),
}
FEATURE_IMPORTANCE = {
    "BS": 0.3516, "SystolicBP": 0.1926, "Age": 0.1589,
    "DiastolicBP": 0.1270, "HeartRate": 0.1030, "BodyTemp": 0.0669,
}

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "random_forest_model.joblib")
_model = joblib.load(_MODEL_PATH)



def predict_risk(values: dict) -> dict:
    """
    values: dict with keys matching FEATURE_ORDER (Age, SystolicBP, ...)
    returns: {"label": str, "probs": {"high risk": float, ...}, "factors": [...]}
    """
    x = [[float(values[k]) for k in FEATURE_ORDER]]
    probs = _model.predict_proba(x)[0]

    prob_map = {RISK_LABELS[i]: float(probs[i]) for i in range(3)}
    label = RISK_LABELS[int(probs.argmax())]

    factors = []
    for k in FEATURE_ORDER:
        lo, hi = FEATURE_RANGE[k]
        rng = hi - lo
        dev = abs(float(values[k]) - LOW_RISK_MEANS[k]) / rng
        factors.append({
            "key": k,
            "score": dev * FEATURE_IMPORTANCE[k],
            "value": float(values[k]),
            "mean": LOW_RISK_MEANS[k],
            "direction": "higher" if float(values[k]) > LOW_RISK_MEANS[k] else "lower",
        })
    factors.sort(key=lambda f: -f["score"])

    return {"label": label, "probs": prob_map, "factors": factors[:3]}
