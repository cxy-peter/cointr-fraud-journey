from __future__ import annotations

from pathlib import Path

import pytest

from cointr_fraud.pipeline import PipelineResult, run_pipeline


@pytest.fixture(scope="session")
def pipeline_result(tmp_path_factory: pytest.TempPathFactory) -> PipelineResult:
    return run_pipeline(Path(tmp_path_factory.mktemp("cointr_outputs")))
