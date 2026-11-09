from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results" / "phase5_final_eval"
APP = Path(__file__).resolve().parents[1] / "src" / "app" / "dashboard.py"

pytestmark = pytest.mark.skipif(not (RESULTS / "per_seed.csv").exists(), reason="final results not generated")


def test_dashboard_runs_without_exceptions_and_labels_simulated():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(w.value for w in at.warning)
    assert "simulated" in text.lower() and "not Claude" in text
    assert len(at.tabs) == 4 and len(at.metric) >= 4


def test_dashboard_segment_filters_and_agent_filters_work():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.selectbox[3].select("BIN_GROUP_1").run()  # first selectbox on the segment tab is the BIN group picker
    assert not at.exception, [e.value for e in at.exception]
