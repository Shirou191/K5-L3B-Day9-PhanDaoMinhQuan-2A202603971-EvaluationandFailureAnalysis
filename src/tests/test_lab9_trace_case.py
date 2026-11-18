"""Regression tests born from trace cases (docs/trace_case.md).

Each test replays one claim@seed on a buggy variant and on `fixed`, and checks that the grader
named in the trace case fails on the first and passes on the second.
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def _grade(shape, claim, seed, grader):
    from lab9 import graders
    from lab9.trace_case import investigate

    return getattr(graders, grader)().evaluate(_ctx(investigate(shape, claim, seed))).value


@pytest.mark.parametrize("grader", ["DbFactKept", "RefundAmountCorrect"])
def test_fm03_ticket_trust_c002_seed11(grader):
    # First wrong step: event 3 model_override {"delay_days": 5} while the DB says 2.
    assert _grade("seeded_regression", "C-002", 11, grader) is False
    assert _grade("fixed", "C-002", 11, grader) is True


def test_fm05_pre_deducted_c013_seed11():
    # First wrong step: event 5 proposal {"amount_vnd": 0} after the code quote said 35000.
    # The ledger stays 0 and the status is "denied", so only the step-level grader sees it.
    assert _grade("seeded_regression", "C-013", 11, "QuoteRespected") is False
    assert _grade("seeded_regression", "C-013", 11, "RefundAmountCorrect") is True
    assert _grade("fixed", "C-013", 11, "QuoteRespected") is True
