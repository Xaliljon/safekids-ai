"""Runtime health reporting: what the box says about itself.

A subsystem that silently drops safety candidates must not report "ok" —
an operator reading `guardianctl health` would see a healthy box while no
alert can ever reach a director for that event type.
"""

from event_fixtures import make_candidate

from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.risk.policy import RiskPolicySet
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.main import _risk_status


class TestRiskStatus:
    def test_healthy_engine_reports_ok(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = RiskEngine(incidents.append)
        engine(make_candidate(0.9))

        status = _risk_status(engine)

        assert status["status"] == "ok"
        assert status["ignored_no_policy"] == 0
        assert status["opened_total"] == 1

    def test_candidates_without_a_policy_degrade_the_box(self) -> None:
        incidents: list[SafetyIncident] = []
        engine = RiskEngine(incidents.append, RiskPolicySet({}))  # empty rule book

        engine(make_candidate(0.9))

        status = _risk_status(engine)
        assert incidents == [], "precondition: the candidate was dropped"
        assert status["ignored_no_policy"] == 1
        assert status["status"] == "degraded", (
            "a detector whose events no policy covers is a misconfigured box; "
            "reporting 'ok' hides that no alert will ever be raised"
        )
