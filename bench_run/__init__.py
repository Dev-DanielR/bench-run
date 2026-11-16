"""bench-run: TOML-driven experiment harness."""

from bench_run.campaign import CampaignRun
from bench_run.config import (
    resolveCampaignConfigPath,
    resolveConfigPath,
    resolveMatrixConfigPath,
    workspace_root,
)
from bench_run.main import main
from bench_run.matrix import MatrixRun
from bench_run.run import PreflightCancel, Run

__all__ = [
    "Run",
    "MatrixRun",
    "CampaignRun",
    "main",
    "PreflightCancel",
    "resolveConfigPath",
    "resolveMatrixConfigPath",
    "resolveCampaignConfigPath",
    "workspace_root",
]

__version__ = "0.1.0"
