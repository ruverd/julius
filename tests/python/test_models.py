"""Read-only client capability discovery."""

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
        assert client["capability"] == "experimental"
        assert client["featureStatus"] == {
            "versionDiscovery": "observe_only",
            "manualUsageImport": "experimental",
            "liveUsageObservation": "unsupported",
            "inputOptimization": "unsupported",
        }
        assert not any(client["capabilities"].values())


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
