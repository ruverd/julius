from datetime import datetime, timedelta, timezone
from decimal import Decimal

from julius.router import ModelChoice, PriceEvidence, TaskBoundary, decide_route


NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def model(name="current", **changes):
    data = dict(endpoint="https://example.test/a", provider="example", requested_model=name,
                actual_model=name, digest="sha1", quantization="q4", tokenizer_id="tok-a",
                state="available_remote",
                location="remote", context_window=8192, supports_tools=True,
                supports_structured_output=True, observed_latency_ms=100,
                observed_concurrency_capacity=2, observed_concurrency_used=0,
                authorization_granted=True, evidence_id=name)
    data.update(changes)
    return ModelChoice(**data)


def boundary(**changes):
    data = dict(boundary_id="turn-1", safe_to_switch=True, requires_tools=True,
                requires_structured_output=True, input_tokens=1000,
                expected_output_tokens=1000, forecast_tokenizer_id="tok-a",
                forecast_evidence_id="forecast-1", minimum_context_tokens=2000,
                allowed_locations=frozenset({"remote", "local"}),
                allowed_endpoints=frozenset({"https://example.test/a", "https://example.test/b"}),
                maximum_latency_ms=300, maximum_spend=Decimal("1"))
    data.update(changes)
    return TaskBoundary(**data)


def price(choice, amount, **changes):
    data = dict(model_identity=choice.identity, input_per_million=Decimal(amount),
                output_per_million=Decimal(amount), effective_at=NOW, source="price-list-2026")
    data.update(changes)
    return PriceEvidence(**data)


def route(candidate, *, current=None, prices=None, task=None):
    current = current or model()
    prices = prices if prices is not None else (price(current, "10"), price(candidate, "2"))
    return decide_route(boundary=task or boundary(), current=current, candidates=(candidate,),
                        prices=prices, now=NOW)


def test_chooses_cheaper_candidate_and_preserves_actual_identity():
    candidate = model("alias", actual_model="real-v2")
    decision = route(candidate)
    assert decision.switched
    assert decision.selected.requested_model == "alias"
    assert decision.selected.actual_model == "real-v2"
    assert decision.predicted_savings == Decimal("0.016")
    assert decision.current_evidence_id == "current"
    assert decision.price_sources == ("price-list-2026", "price-list-2026")


def test_alias_at_other_endpoint_cannot_borrow_price():
    candidate = model("alias", endpoint="https://example.test/b")
    other = model("alias")
    assert not route(candidate, prices=(price(model(), "10"), price(other, "2"))).switched


def test_quantization_cannot_borrow_price():
    candidate = model("small", quantization="q8")
    other = model("small", quantization="q4")
    assert not route(candidate, prices=(price(model(), "10"), price(other, "2"))).switched


def test_unknown_or_stale_price_keeps_current():
    candidate = model("small")
    assert not route(candidate, prices=(price(model(), "10"),)).switched
    assert not route(candidate, prices=(price(model(), "10"), price(candidate, "2",
                                            effective_at=NOW - timedelta(days=31)))).switched


def test_unloaded_or_unadmitted_local_candidate_is_rejected():
    candidate = model("local", location="local", state="installed", hardware_admitted=True)
    assert not route(candidate).switched
    assert not route(candidate.model_copy(update={"state": "loaded", "hardware_admitted": None})).switched


def test_capability_limits_and_authorization_fail_closed():
    candidate = model("small")
    for change in ({"supports_tools": None}, {"supports_structured_output": False},
                   {"context_window": None}, {"observed_latency_ms": None},
                   {"observed_concurrency_used": 2}, {"authorization_granted": None}):
        assert not route(candidate.model_copy(update=change)).switched


def test_budget_risk_margin_and_boundary():
    candidate = model("small")
    assert not route(candidate, task=boundary(maximum_spend=Decimal("0.003"))).switched
    assert not route(candidate, task=boundary(safe_to_switch=False)).switched
    assert route(candidate, prices=(price(model(), "10"), price(candidate, "8")),
                 task=boundary(minimum_savings_fraction=Decimal("0.25"))).switched is False


def test_unknown_current_price_and_unverified_current_keep_current():
    candidate = model("small")
    assert route(candidate, prices=(price(candidate, "2"),)).reason == "current_price_unknown"
    current = model(authorization_granted=None)
    assert route(candidate, current=current).reason == "current_eligibility_unverified"


def test_dispatch_verdict_denies_unverified_current_even_when_kept():
    candidate = model("small", supports_tools=False)
    current = model(authorization_granted=None)
    decision = route(candidate, current=current)
    assert decision.selected == current
    assert decision.dispatch_allowed is False


def test_dispatch_verdict_denies_unknown_or_exceeded_budget():
    candidate = model("small", supports_tools=False)
    unknown = route(candidate, prices=(), task=boundary(maximum_spend=Decimal("1")))
    assert unknown.dispatch_allowed is False
    exceeded = route(candidate, task=boundary(maximum_spend=Decimal("0.001")))
    assert exceeded.reason == "budget_exceeded_no_eligible_alternative"
    assert exceeded.dispatch_allowed is False


def test_unsafe_switch_can_still_allow_verified_current_dispatch():
    decision = route(model("small"), task=boundary(safe_to_switch=False))
    assert decision.switched is False
    assert decision.dispatch_allowed is True


def test_different_or_missing_candidate_tokenizer_cannot_borrow_forecast():
    assert not route(model("small", tokenizer_id="tok-b")).switched
    assert not route(model("small", tokenizer_id=None)).switched


def test_unknown_current_tokenizer_denies_dispatch_and_cost_claim():
    current = model(tokenizer_id=None)
    decision = route(model("small"), current=current)
    assert decision.dispatch_allowed is False
    assert decision.current_predicted_cost is None
    assert decision.predicted_savings is None


def test_forecast_provenance_is_recorded():
    decision = route(model("small"))
    assert decision.forecast_evidence_id == "forecast-1"
