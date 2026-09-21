from julius.optimizer import optimize


LINE = "neutral status line with enough characters to reduce and some additional ordinary status detail"
CONTENT = "\n".join([LINE] * 6)
RECOVERY = {"artifactId": "12345678-1234-1234-1234-123456789abc", "available": True}
POLICY = {"mode": "safe", "version": "1.0.0", "approved": True}


def test_safe_native_candidate_or_explicit_unavailable():
    result = optimize(
        {"projectId": "p", "category": "tool_output", "content": CONTENT, "recovery": RECOVERY},
        POLICY,
    )
    assert result["receipt"]["realizedSavings"] is None
    assert result["receipt"]["evidence"] == "heuristic_estimate"
    if result["receipt"]["reason"] == "native_unavailable":
        assert result["candidate"] == CONTENT
    else:
        assert result["receipt"]["applied"]
        assert RECOVERY["artifactId"] in result["candidate"]


def test_native_matches_frozen_typescript_reduction_corpus():
    from julius._native import compress_repeated_lines

    marker = f"[repeated exact line 2/3; restore artifact {RECOVERY['artifactId']}]"
    line = "ordinary neutral line that is long enough for a useful deterministic reduction and additional ordinary status detail"
    expected = (
        f"{line}\n{marker}\n[repeated exact line 3/3; restore artifact {RECOVERY['artifactId']}]"
    )
    # TS and Rust both compare UTF-8 byte length before returning a reduction.
    original = "\n".join([line] * 3)
    assert compress_repeated_lines(original, RECOVERY["artifactId"]) == (
        expected if len(expected.encode()) < len(original.encode()) else original
    )
    assert (
        compress_repeated_lines("short\nshort\nshort", RECOVERY["artifactId"])
        == "short\nshort\nshort"
    )
    assert (
        compress_repeated_lines(
            "opaque 🔒 line\nopaque 🔒 line\nopaque 🔒 line", RECOVERY["artifactId"]
        )
        == "opaque 🔒 line\nopaque 🔒 line\nopaque 🔒 line"
    )


def test_fail_closed_and_protected():
    context = {
        "projectId": "p",
        "category": "tool_output",
        "content": CONTENT,
        "recovery": RECOVERY,
    }
    assert optimize(context, {**POLICY, "disabled": True})["receipt"]["reason"] == "policy_disabled"
    assert (
        optimize(context, {**POLICY, "approved": False})["receipt"]["reason"] == "approval_required"
    )
    assert (
        optimize({**context, "recovery": None}, POLICY)["receipt"]["reason"] == "recovery_required"
    )
    assert (
        optimize({**context, "content": "FAIL assertion\n" + CONTENT}, POLICY)["receipt"]["reason"]
        == "protected_content"
    )
    assert optimize(context, {**POLICY, "mode": "observe"})["candidate"] == CONTENT
