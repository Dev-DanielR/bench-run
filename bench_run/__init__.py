"""bench-run: TOML-driven experiment harness."""

from bench_run.config import (
    resolve_campaign_config_path,
    resolve_config_path,
    resolve_matrix_config_path,
    workspace_root,
)
from bench_run.layers import CampaignRun, MatrixRun, PreflightCancel, Run
from bench_run.main import main

__all__ = [
    "Run",
    "MatrixRun",
    "CampaignRun",
    "main",
    "PreflightCancel",
    "resolve_config_path",
    "resolve_matrix_config_path",
    "resolve_campaign_config_path",
    "workspace_root",
]

__version__ = "0.1.0"
