"""Realistic trading environment for reinforcement learning.

A self-contained, gym-style env (no hard dependency on gymnasium / SB3 — it
subclasses `gymnasium.Env` only if it is installed). The point is that the
*reward already nets out the frictions a live perp bot pays*: taker fees on every
position change and perpetual funding on the held notional. Training a policy
that ignores these is how the noches bots overfit; this env makes the costs part
of the objective. Built to be wrapped in walk-forward folds (train on one slice,
evaluate out-of-sample on the next).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:                       # optional: only used to expose a Gymnasium-compatible class
    import gymnasium as gym
    _HAS_GYM = True
except Exception:          # pragma: no cover
    _HAS_GYM = False


class TradingEnv:
    """Discrete-action perp trading env.

    actions: 0 = short(-1), 1 = flat(0), 2 = long(+1)   (flat/long only if not allow_short)
    reward : held_position * next_bar_return − turnover*cost − funding_on_position
    """

    def __init__(
        self, df: pd.DataFrame, feature_cols: list[str], *, window: int = 32,
        taker_fee_bps: float = 6.0, slippage_bps: float = 2.0,
        funding_rate_8h: float = 0.0001, hours_per_bar: float = 0.25,
        allow_short: bool = True,
    ) -> None:
        self.df = df.reset_index(drop=True)
        self.feature_cols = feature_cols
        self.window = window
        self.cost = (taker_fee_bps + slippage_bps) / 1e4
        self.funding_per_bar = funding_rate_8h * (hours_per_bar / 8.0)
        self.allow_short = allow_short
        self.actions = (-1, 0, 1) if allow_short else (0, 1)
        self._feat = self.df[feature_cols].to_numpy(dtype=float)
        self._ret = self.df["close"].pct_change().fillna(0.0).to_numpy()
        self.n = len(self.df)
        self.reset()

    @property
    def observation_dim(self) -> int:
        return self.window * len(self.feature_cols) + 1  # +1 = current position

    @property
    def n_actions(self) -> int:
        return len(self.actions)

    def reset(self, start: int | None = None):
        self.t = self.window if start is None else max(start, self.window)
        self.position = 0.0
        self.equity = 1.0
        return self._obs()

    def _obs(self) -> np.ndarray:
        win = self._feat[self.t - self.window:self.t].ravel()
        return np.concatenate([win, [self.position]]).astype(np.float32)

    def step(self, action_idx: int):
        target = float(self.actions[int(action_idx)])
        turnover = abs(target - self.position)
        nxt = self._ret[self.t] if self.t < self.n else 0.0
        reward = target * nxt - turnover * self.cost - abs(target) * self.funding_per_bar
        self.position = target
        self.equity *= (1.0 + reward)
        self.t += 1
        done = self.t >= self.n - 1
        return (self._obs() if not done else None), float(reward), done, {"equity": self.equity}


def evaluate_policy(env: TradingEnv, policy_fn) -> dict:
    """Roll a policy(obs)->action_idx through the env once; report net metrics."""
    obs = env.reset()
    rewards: list[float] = []
    done = False
    while not done:
        a = policy_fn(obs)
        obs, r, done, _info = env.step(a)
        rewards.append(r)
    arr = np.array(rewards)
    sd = arr.std(ddof=1) if arr.size > 1 else 0.0
    return {
        "total_return": float(env.equity - 1.0),
        "sharpe_per_bar": float(arr.mean() / sd) if sd > 0 else 0.0,
        "n_steps": int(arr.size),
        "final_equity": float(env.equity),
    }


if _HAS_GYM:  # pragma: no cover - exposed only when gymnasium is installed
    class GymTradingEnv(gym.Env):
        """Gymnasium adapter so the env can be dropped into Stable-Baselines3."""

        metadata = {"render_modes": []}  # noqa: RUF012 (gymnasium convention)

        def __init__(self, df, feature_cols, **kw):
            super().__init__()
            self._env = TradingEnv(df, feature_cols, **kw)
            self.action_space = gym.spaces.Discrete(self._env.n_actions)
            self.observation_space = gym.spaces.Box(
                low=-np.inf, high=np.inf, shape=(self._env.observation_dim,), dtype=np.float32)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return self._env.reset(), {}

        def step(self, action):
            obs, r, done, info = self._env.step(action)
            if obs is None:
                obs = np.zeros(self._env.observation_dim, dtype=np.float32)
            return obs, r, done, False, info
