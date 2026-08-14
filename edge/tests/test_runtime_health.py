"""Runtime health reporting: what the box says about itself.

A subsystem that silently drops safety candidates must not report "ok" —
an operator reading `guardianctl health` would see a healthy box while no
alert can ever reach a director for that event type.
"""

from pathlib import Path

from event_fixtures import make_candidate

from guardian_edge.application.risk.engine import RiskEngine
from guardian_edge.application.risk.policy import RiskPolicySet
from guardian_edge.domain.incident import SafetyIncident
from guardian_edge.domain.zone import ScheduleWindow, Weekday, Zone, ZonePoint
from guardian_edge.main import _clock_status, _risk_status
from guardian_edge.ops.clock import ClockStatus, ClockTrust


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


class TestClockStatus:
    """A clock fault the box does not depend on is not a fault. A box that
    reports degraded forever is a box whose health nobody reads."""

    UNTRUSTED = ClockStatus(trusted=False, reason="never synchronized")

    def _clock(self, status: ClockStatus) -> ClockTrust:
        trust = ClockTrust(Path("/nonexistent"))
        trust.status = lambda now=None: status  # type: ignore[method-assign]
        return trust

    def _zone(self, *, scheduled: bool) -> Zone:
        return Zone(
            zone_id="z",
            camera_id="cam-1",
            name="Zone",
            polygon=(ZonePoint(0.1, 0.1), ZonePoint(0.9, 0.1), ZonePoint(0.9, 0.9)),
            active_windows=(
                (ScheduleWindow(days=frozenset(Weekday), start_minute=780, end_minute=900),)
                if scheduled
                else ()
            ),
        )

    def test_an_untrusted_clock_with_no_zones_at_all_is_not_degraded(self) -> None:
        payload = _clock_status(self._clock(self.UNTRUSTED), [])

        assert payload["status"] == "ok"
        assert payload["trusted"] is False, "the fault is still reported, just not escalated"
        assert payload["reason"]

    def test_an_untrusted_clock_with_only_always_on_zones_is_not_degraded(self) -> None:
        payload = _clock_status(self._clock(self.UNTRUSTED), [self._zone(scheduled=False)])
        assert payload["status"] == "ok"

    def test_an_untrusted_clock_with_a_scheduled_zone_is_degraded(self) -> None:
        payload = _clock_status(self._clock(self.UNTRUSTED), [self._zone(scheduled=True)])

        assert payload["status"] == "degraded", (
            "here the hours really are being ignored, so the box must say so"
        )

    def test_a_trusted_clock_is_ok_either_way(self) -> None:
        trusted = ClockStatus(trusted=True, reason="synchronized", timezone_name="UTC")
        assert _clock_status(self._clock(trusted), [self._zone(scheduled=True)])["status"] == "ok"
