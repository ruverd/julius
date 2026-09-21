import json
import pytest

from julius.jev import JevAnswer, ShadowPolicy, TypeSafeGateway, shadow_decide


class FakeGateway:
    def __init__(self, answer: JevAnswer | Exception):
        self.answer = answer
        self.calls = []

    def choose(self, state, eligible_actions, timeout_seconds):
        self.calls.append((state, eligible_actions, timeout_seconds))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_shadow_never_applies_and_filters_state():
    gateway = FakeGateway(JevAnswer("compress", 0.95, 0.01))
    receipt = shadow_decide(
        state={"input_tokens": 100, "secret": "do not send", "project_id": "private"},
        eligible_actions=("keep", "compress"),
        policy=ShadowPolicy(enabled=True, max_cost_usd=0.02),
        gateway=gateway,
    )
    assert receipt.applied_action == "keep"
    assert receipt.proposed_action == "compress"
    assert gateway.calls[0][0] == {"input_tokens": 100}


def test_timeout_falls_back():
    gateway = FakeGateway(TimeoutError())
    receipt = shadow_decide(state={}, eligible_actions=("keep",), policy=ShadowPolicy(enabled=True, max_cost_usd=1), gateway=gateway)
    assert receipt.reason == "timeout"
    assert receipt.applied_action == "keep"


def test_ineligible_answer_falls_back():
    gateway = FakeGateway(JevAnswer("retrieve", 0.99, 0.01))
    receipt = shadow_decide(state={}, eligible_actions=("keep", "compress"), policy=ShadowPolicy(enabled=True, max_cost_usd=1), gateway=gateway)
    assert receipt.reason == "ineligible_choice"
    assert receipt.proposed_action is None


def test_budget_prevents_call_and_excess_falls_back():
    gateway = FakeGateway(JevAnswer("compress", 0.99, 2.0))
    policy = ShadowPolicy(enabled=True, max_cost_usd=0)
    receipt = shadow_decide(state={}, eligible_actions=("compress",), policy=policy, gateway=gateway)
    assert receipt.reason == "budget_unavailable"
    assert not gateway.calls
    receipt = shadow_decide(state={}, eligible_actions=("compress",), policy=ShadowPolicy(enabled=True, max_cost_usd=1), gateway=gateway)
    assert receipt.reason == "budget_exceeded"
    assert receipt.applied_action == "keep"


def test_disabled_never_calls_gateway():
    gateway = FakeGateway(JevAnswer("compress", 1, 0))
    assert shadow_decide(state={}, eligible_actions=("compress",), policy=ShadowPolicy(), gateway=gateway).reason == "disabled"
    assert not gateway.calls


class FixtureTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, body, api_key, timeout_seconds):
        self.calls.append((json.loads(body), api_key, timeout_seconds))
        return json.dumps(self.response).encode()


def test_typesafe_protocol_and_usage():
    transport = FixtureTransport({
        "model": "jev-latest",
        "answers": {"action": {"choice": "compress", "confidence": 0.9}},
        "usage": {"input_tokens": 200, "output_tokens": 10},
    })
    gateway = TypeSafeGateway("private-key", input_usd_per_million=1, output_usd_per_million=2, transport=transport)
    receipt = shadow_decide(
        state={"input_tokens": 1000, "secret": "hidden"}, eligible_actions=("keep", "compress"),
        policy=ShadowPolicy(enabled=True, max_cost_usd=1), gateway=gateway,
    )
    body, key, timeout = transport.calls[0]
    assert len(transport.calls) == 1
    assert key == "private-key" and timeout == 1
    assert body["model"] == "jev-latest"
    assert body["state"] == {"input_tokens": 1000}
    assert body["questions"]["action"]["type"] == "choice"
    assert set(body["questions"]["action"]["criteria"]) == {"keep", "compress"}
    assert receipt.applied_action == "keep"
    assert receipt.proposed_action == "compress"
    assert receipt.input_tokens == 200 and receipt.output_tokens == 10
    assert receipt.actual_model == "jev-latest"
    assert receipt.cost_usd == 0.00022


def test_unknown_price_retains_provider_usage_and_falls_back():
    transport = FixtureTransport({
        "model": "jev-latest", "answers": {"action": {"choice": "compress", "confidence": 0.9}},
        "usage": {"input_tokens": 20, "output_tokens": 1},
    })
    receipt = shadow_decide(
        state={}, eligible_actions=("compress",), policy=ShadowPolicy(enabled=True, max_cost_usd=1),
        gateway=TypeSafeGateway("key", transport=transport),
    )
    assert receipt.reason == "cost_unknown"
    assert receipt.proposed_action == "compress"
    assert receipt.applied_action == "keep"
    assert receipt.input_tokens == 20 and receipt.output_tokens == 1
    assert receipt.cost_usd is None


def test_invalid_usage_rejected():
    transport = FixtureTransport({"answers": {"action": {"choice": "keep", "confidence": 1}}, "usage": {"input_tokens": True}})
    receipt = shadow_decide(
        state={}, eligible_actions=("keep",), policy=ShadowPolicy(enabled=True, max_cost_usd=1),
        gateway=TypeSafeGateway("key", transport=transport),
    )
    assert receipt.reason == "gateway_error"


@pytest.mark.parametrize("api_key", ["", " key", "key\nInjected: yes", "key\x00bad"])
def test_invalid_api_key_rejected(api_key):
    with pytest.raises(ValueError):
        TypeSafeGateway(api_key)


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -1])
def test_invalid_price_rate_rejected(rate):
    with pytest.raises(ValueError):
        TypeSafeGateway("key", input_usd_per_million=rate)
