"""Matplotlib chart helpers for generated reports."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def save_equity_curve(equity: pd.Series, output_path: Path, title: str = "Equity Curve") -> Path:
    """Save a publication-friendly equity curve chart."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    equity.reset_index(drop=True).plot(ax=ax, color="#1f77b4", linewidth=1.8)
    ax.set_title(title)
    ax.set_xlabel("Observation")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_drawdown_chart(equity: pd.Series, output_path: Path, title: str = "Drawdown") -> Path:
    """Save a drawdown chart for a strategy or portfolio."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    drawdown = equity / equity.cummax() - 1
    fig, ax = plt.subplots(figsize=(11, 4))
    drawdown.reset_index(drop=True).plot(ax=ax, color="#b22222", linewidth=1.4)
    ax.set_title(title)
    ax.set_xlabel("Observation")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path
