"""Model loading and inference for the Phase 4 trading agent models."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from config.settings import Paths

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ModelPrediction:
    direction: int
    direction_prob: float
    sl_bin: str
    trail_bin: str
    trail_tf: str
    phase1_target: float
    confidence: float
    trade_class: str | None = None
    should_trade: bool = True


class NiftyPredictor:
    def __init__(self) -> None:
        self.instrument: str | None = None
        self.selected_features: list[str] = []
        self.direction_model = None
        self.trade_class_model = None
        self.sl_bin_model = None
        self.trail_bin_model = None
        self.trail_tf_model = None
        self.phase1_target_model = None
        self.trade_class_encoder = None
        self.sl_bin_encoder = None
        self.trail_bin_encoder = None
        self.trail_tf_encoder = None

    def load(self, artifacts_dir: str | Path, instrument: str) -> None:
        artifacts = Path(artifacts_dir)
        instrument_key = instrument.upper()

        trade_class_path = artifacts / f"{instrument_key}_trade_class.joblib"
        trade_class_encoder_path = artifacts / f"{instrument_key}_trade_class_encoder.joblib"
        direction_path = artifacts / f"{instrument_key}_direction.joblib"
        self.trade_class_model = None
        self.trade_class_encoder = None
        self.direction_model = None
        if trade_class_path.exists() and trade_class_encoder_path.exists():
            self.trade_class_model = joblib.load(trade_class_path)
            self.trade_class_encoder = joblib.load(trade_class_encoder_path)
        elif direction_path.exists():
            self.direction_model = joblib.load(direction_path)
        else:
            raise FileNotFoundError(
                f"Expected either {trade_class_path.name} or {direction_path.name} in {artifacts}"
            )
        self.sl_bin_model = joblib.load(artifacts / f"{instrument_key}_sl_bin.joblib")
        self.sl_bin_encoder = joblib.load(artifacts / f"{instrument_key}_sl_bin_encoder.joblib")
        self.trail_bin_model = joblib.load(artifacts / f"{instrument_key}_trail_bin.joblib")
        self.trail_bin_encoder = joblib.load(artifacts / f"{instrument_key}_trail_bin_encoder.joblib")
        self.trail_tf_model = joblib.load(artifacts / f"{instrument_key}_trail_tf.joblib")
        self.trail_tf_encoder = joblib.load(artifacts / f"{instrument_key}_trail_tf_encoder.joblib")
        self.phase1_target_model = joblib.load(artifacts / f"{instrument_key}_phase1_target.joblib")

        selected_features_path = artifacts / f"{instrument_key}_selected_features.json"
        self.selected_features = json.loads(selected_features_path.read_text(encoding="utf-8"))
        self.instrument = instrument_key

        logger.info("Loaded model artifacts for %s from %s", instrument_key, artifacts)

    def predict(self, feature_row: pd.DataFrame) -> ModelPrediction:
        self._validate_loaded()

        if len(feature_row) != 1:
            raise ValueError("feature_row must contain exactly one row.")

        missing = [column for column in self.selected_features if column not in feature_row.columns]
        if missing:
            raise ValueError(f"Missing required features for prediction: {missing}")

        x = feature_row.reindex(columns=self.selected_features).copy()

        trade_class = None
        should_trade = True
        if self.trade_class_model is not None and self.trade_class_encoder is not None:
            trade_pred = self.trade_class_model.predict(x)
            trade_proba = self.trade_class_model.predict_proba(x)[0]
            trade_class = str(self.trade_class_encoder.inverse_transform(trade_pred)[0])
            trade_classes = [
                str(label)
                for label in self.trade_class_encoder.inverse_transform(
                    np.arange(len(self.trade_class_encoder.classes_))
                )
            ]
            trade_prob_map = {label: float(prob) for label, prob in zip(trade_classes, trade_proba)}
            ce_prob = trade_prob_map.get("CE_TP_FIRST", 0.0)
            pe_prob = trade_prob_map.get("PE_TP_FIRST", 0.0)
            if trade_class == "CE_TP_FIRST":
                direction_pred = 1
            elif trade_class == "PE_TP_FIRST":
                direction_pred = 0
            else:
                direction_pred = 1 if ce_prob >= pe_prob else 0
            direction_mass = ce_prob + pe_prob
            prob_up = ce_prob / direction_mass if direction_mass > 0 else 0.5
            confidence = trade_prob_map.get(trade_class, 0.0)
            should_trade = trade_class != "NO_TRADE"
        else:
            direction_pred = int(self.direction_model.predict(x)[0])
            direction_proba = self.direction_model.predict_proba(x)[0]

            classes = getattr(self.direction_model.named_steps["model"], "classes_", np.array([0, 1]))
            class_to_prob = {int(label): float(prob) for label, prob in zip(classes, direction_proba)}
            prob_up = class_to_prob.get(1, 0.0)
            confidence = max(prob_up, 1.0 - prob_up)

        sl_bin_encoded = self.sl_bin_model.predict(x)
        trail_bin_encoded = self.trail_bin_model.predict(x)
        trail_tf_encoded = self.trail_tf_model.predict(x)
        phase1_value = float(self.phase1_target_model.predict(x)[0])

        sl_bin = str(self.sl_bin_encoder.inverse_transform(sl_bin_encoded)[0])
        trail_bin = str(self.trail_bin_encoder.inverse_transform(trail_bin_encoded)[0])
        trail_tf = str(self.trail_tf_encoder.inverse_transform(trail_tf_encoded)[0])

        return ModelPrediction(
            direction=direction_pred,
            direction_prob=float(prob_up),
            sl_bin=sl_bin,
            trail_bin=trail_bin,
            trail_tf=trail_tf,
            phase1_target=phase1_value,
            confidence=float(confidence),
            trade_class=trade_class,
            should_trade=bool(should_trade),
        )

    def _validate_loaded(self) -> None:
        required = [
            self.sl_bin_model,
            self.trail_bin_model,
            self.trail_tf_model,
            self.phase1_target_model,
            self.sl_bin_encoder,
            self.trail_bin_encoder,
            self.trail_tf_encoder,
        ]
        if self.direction_model is None and (self.trade_class_model is None or self.trade_class_encoder is None):
            raise RuntimeError("Classification artifacts are not loaded. Call load(artifacts_dir, instrument) first.")
        if any(item is None for item in required) or not self.selected_features:
            raise RuntimeError("Models are not loaded. Call load(artifacts_dir, instrument) first.")


nifty_predictor = NiftyPredictor()
