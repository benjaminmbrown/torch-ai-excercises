from __future__ import annotations
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from typing import Tuple


class WindowedDataset:
    """Sliding-window feature construction for univariate time series."""

    def __init__(self, window: int = 24):
        self.window = window

    def transform(self, series: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if len(series) <= self.window:
            raise ValueError(f"Series length {len(series)} must exceed window {self.window}")
        X, y = [], []
        for i in range(len(series) - self.window):
            window_slice = series[i : i + self.window]
            X.append(self._features(window_slice))
            y.append(series[i + self.window])
        return np.array(X), np.array(y)

    def _features(self, w: np.ndarray) -> np.ndarray:
        """Extract statistical features from a window: lag values + stats."""
        lag_feats = w[-6:]  # last 6 observations as lag features
        stat_feats = np.array([
            w.mean(), w.std(), w.min(), w.max(),
            w[-1] - w[0],          # trend slope proxy
            np.median(w),           # robust location
            np.percentile(w, 25),  # IQR bounds
            np.percentile(w, 75),
        ])
        return np.concatenate([lag_feats, stat_feats])


class ForecastPipeline:
    """End-to-end forecast pipeline: windowing -> scaling -> Ridge regression -> multi-step."""

    def __init__(self, window: int = 24, alpha: float = 1.0):
        self.window = window
        self.dataset = WindowedDataset(window=window)
        self.scaler_X = StandardScaler()
        self.scaler_y = StandardScaler()
        self.model = Ridge(alpha=alpha)
        self._fitted = False

    def fit(self, series: np.ndarray) -> "ForecastPipeline":
        X, y = self.dataset.transform(series)
        Xs = self.scaler_X.fit_transform(X)
        ys = self.scaler_y.fit_transform(y.reshape(-1, 1)).ravel()
        self.model.fit(Xs, ys)
        self._fitted = True
        return self

    def predict(self, series: np.ndarray, horizon: int) -> Tuple[list, list, list]:
        if not self._fitted:
            self.fit(series)  # auto-fit if not yet fitted
        history = series.tolist()
        predictions: list[float] = []
        residual_std = self._estimate_residual_std(series)

        for _ in range(horizon):
            window_arr = np.array(history[-self.window:])
            feats = self.dataset._features(window_arr).reshape(1, -1)
            feats_s = self.scaler_X.transform(feats)
            pred_s = self.model.predict(feats_s)
            pred = float(self.scaler_y.inverse_transform(pred_s.reshape(-1, 1))[0, 0])
            predictions.append(round(pred, 4))
            history.append(pred)

        ci_mult = 1.96 * residual_std
        lower = [round(p - ci_mult, 4) for p in predictions]
        upper = [round(p + ci_mult, 4) for p in predictions]
        return predictions, lower, upper

    def _estimate_residual_std(self, series: np.ndarray) -> float:
        try:
            X, y = self.dataset.transform(series)
            Xs = self.scaler_X.transform(X)
            ys_pred_s = self.model.predict(Xs)
            ys_pred = self.scaler_y.inverse_transform(ys_pred_s.reshape(-1, 1)).ravel()
            return float(np.std(y - ys_pred))
        except Exception:
            return float(np.std(series) * 0.1)
