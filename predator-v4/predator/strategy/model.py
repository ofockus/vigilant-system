"""
Lightweight ML model for entry confidence scoring.

Uses scikit-learn GradientBoosting (fast inference <5ms).
Training happens offline via backtest. Model saved as joblib.
Inference returns (direction, confidence) for each tick.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from loguru import logger
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from .features import FeatureVector

MODEL_PATH = Path("data/model.joblib")
SCALER_PATH = Path("data/scaler.joblib")


class PredictorModel:
    """ML entry signal with confidence score."""

    def __init__(self) -> None:
        self.model: GradientBoostingClassifier | None = None
        self.scaler: StandardScaler | None = None
        self._loaded = False

    def load(self, model_path: Path | None = None, scaler_path: Path | None = None) -> bool:
        """Load trained model from disk."""
        mp = model_path or MODEL_PATH
        sp = scaler_path or SCALER_PATH

        if mp.exists() and sp.exists():
            try:
                self.model = joblib.load(mp)
                self.scaler = joblib.load(sp)
                self._loaded = True
                logger.info("ML model loaded from {}", mp)
                return True
            except Exception as e:
                logger.warning("Failed to load model: {}", e)

        logger.info("No trained model found — using heuristic fallback")
        return False

    def train(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Train model on feature matrix X and labels y.

        y should be: 1 = profitable long, -1 = profitable short, 0 = no trade/loss
        Returns training metrics.
        """
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Convert to binary classification for confidence
        # 1 = profitable trade (any direction), 0 = not
        y_binary = (y != 0).astype(int)

        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            min_samples_leaf=20,
            random_state=42,
        )
        self.model.fit(X_scaled, y_binary)
        self._loaded = True

        # Metrics
        train_acc = self.model.score(X_scaled, y_binary)
        importances = dict(zip(FeatureVector.feature_names(), self.model.feature_importances_))
        top_features = sorted(importances.items(), key=lambda x: -x[1])[:5]

        logger.info("Model trained | acc={:.3f} | top features: {}", train_acc, top_features)

        return {"accuracy": train_acc, "top_features": dict(top_features)}

    def save(self, model_path: Path | None = None, scaler_path: Path | None = None) -> None:
        mp = model_path or MODEL_PATH
        sp = scaler_path or SCALER_PATH
        mp.parent.mkdir(parents=True, exist_ok=True)

        if self.model is not None:
            joblib.dump(self.model, mp)
        if self.scaler is not None:
            joblib.dump(self.scaler, sp)
        logger.info("Model saved to {}", mp)

    def predict(self, fv: FeatureVector) -> tuple[int, float]:
        """Predict direction and confidence.

        Returns:
            (direction, confidence) where direction is 1 (long), -1 (short), 0 (no trade)
            and confidence is 0.0 to 1.0.
        """
        if not self._loaded or self.model is None or self.scaler is None:
            return self._heuristic_predict(fv)

        X = fv.to_array().reshape(1, -1)
        X_scaled = self.scaler.transform(X)

        # Probability of "profitable trade"
        proba = self.model.predict_proba(X_scaled)[0]
        confidence = float(proba[1]) if len(proba) > 1 else 0.5

        # Direction from flow + momentum features
        direction = self._direction_from_features(fv)

        return direction, confidence

    def _direction_from_features(self, fv: FeatureVector) -> int:
        """Determine trade direction from directional features."""
        score = (
            fv.book_imbalance_5 * 0.25
            + fv.flow_delta * 0.25
            + fv.velocity * 0.02  # velocity in bps, scale down
            + fv.ret_1s * 0.001
            + fv.book_pressure * 0.20
        )
        if score > 0.05:
            return 1
        elif score < -0.05:
            return -1
        return 0

    def _heuristic_predict(self, fv: FeatureVector) -> tuple[int, float]:
        """Fallback when no ML model is trained."""
        # Score from multiple signals
        signals = [
            fv.book_imbalance_5,
            fv.flow_delta,
            np.tanh(fv.velocity * 0.1),
            fv.book_pressure,
            np.tanh(fv.ret_1s * 0.01),
        ]

        # Direction: majority vote
        long_votes = sum(1 for s in signals if s > 0.05)
        short_votes = sum(1 for s in signals if s < -0.05)

        if long_votes >= 3:
            direction = 1
        elif short_votes >= 3:
            direction = -1
        else:
            direction = 0

        # Confidence from agreement + signal strength
        agreement = max(long_votes, short_votes) / len(signals)
        strength = abs(sum(signals)) / len(signals)
        confidence = min(agreement * 0.6 + strength * 0.4, 1.0)

        return direction, confidence
