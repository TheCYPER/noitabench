"""Game 1 of a family is kept between evaluations (`metrics/growth.py`); no test may see another's."""

import pytest
from noitabench.eval.metrics.growth import clear_baselines


@pytest.fixture(autouse=True)
def fresh_baselines():
    clear_baselines()
    yield
    clear_baselines()
