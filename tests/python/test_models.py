"""Read-only client capability discovery."""

import pytest
from pydantic import ValidationError

from julius.adapter_capabilities import AdapterCapabilities, capabilities_for_client
from julius.models import doctor


def test_doctor_classifies_exact_observed_versions(monkeypatch):
    monkeypatch.setattr("julius.models.probe_local_protocol", lambda: {
        "scope": "local_protocol", "available": True,
    })
    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    observed = {"claude": "2.1.278 (Claude Code)\n", "codex": "codex-cli 0.154.0\n"}

    def probe(argv, **kwargs):
        assert argv[1:] == ["--version"]
        assert kwargs["timeout"] == 2
        return Completed(observed[argv[0]])

    monkeypatch.setattr("julius.models.subprocess.run", probe)
    diagnosis = doctor()
    clients = diagnosis["clients"]
    assert diagnosis["localProtocolProbe"]["scope"] == "local_protocol"
    for client in clients:
        assert client["capability"] == (
            "experimental" if client["name"] == "claude" else "observe_only"
        )
        manifest = client["adapterCapabilities"]
        assert manifest["clientVersion"] == (
            "2.1.278" if client["name"] == "claude" else "0.154.0"
        )
        assert manifest["canObserveUsage"] is True
        assert manifest["canReplaceToolOutput"] is (client["name"] == "claude")
        assert manifest["canObserveCompleteRequest"] is False
        assert manifest["canRouteRequests"] is False
        assert manifest["canPreserveApprovalFlow"] is False
        assert manifest["supportedProtocolVersions"] == []
        assert client["featureStatus"] == {
            "versionDiscovery": "observe_only",
            "manualUsageImport": "experimental",
            "liveUsageObservation": "experimental",
            "inputOptimization": "experimental" if client["name"] == "claude" else "unsupported",
        }
        assert "historical" in client["adapterEvidenceScope"]
        assert "client not invoked" in client["featureStatusScope"]


def test_doctor_unknown_version_has_no_import_claim(monkeypatch):
    monkeypatch.setattr("julius.models.probe_local_protocol", lambda: {
        "scope": "local_protocol", "available": False,
    })
    class Completed:
        returncode = 0
        stdout = "codex-cli 0.155.0\n"
        stderr = ""

    monkeypatch.setattr("julius.models.subprocess.run", lambda *args, **kwargs: Completed())
    for client in doctor()["clients"]:
        assert client["capability"] == "unsupported"
        assert client["featureStatus"]["manualUsageImport"] == "unsupported"
        assert client["adapterCapabilities"]["clientVersion"] is None
        assert client["adapterCapabilities"]["canObserveUsage"] is False


def test_capability_manifest_rejects_unsupported_mutation_claim() -> None:
    unsupported = capabilities_for_client("codex", None)
    with pytest.raises(ValidationError, match="Unsupported adapter"):
        AdapterCapabilities.model_validate({
            **unsupported.model_dump(), "canReplaceToolOutput": True,
        })
    observed = capabilities_for_client("codex", "0.154.0")
    with pytest.raises(ValidationError, match="Observe-only"):
        AdapterCapabilities.model_validate({
            **observed.model_dump(), "canRouteRequests": True,
        })


def test_doctor_does_not_trust_version_substring(monkeypatch) -> None:
    monkeypatch.setattr("julius.models.probe_local_protocol", lambda: {"scope": "local_protocol"})

    class Completed:
        returncode = 0
        stdout = "codex-cli 0.154.0 modified\n"
        stderr = ""

    monkeypatch.setattr("julius.models.subprocess.run", lambda *args, **kwargs: Completed())
    codex = next(client for client in doctor()["clients"] if client["name"] == "codex")
    assert codex["capability"] == "unsupported"
    assert codex["adapterCapabilities"]["clientVersion"] is None
