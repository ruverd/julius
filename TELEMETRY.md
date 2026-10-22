# Telemetry

Julius telemetry is off by default. No telemetry key or collector endpoint is embedded in the source or package, and installation does not send an event.

Self-hosted telemetry requires explicit configuration of both `JULIUS_POSTHOG_KEY` and `JULIUS_POSTHOG_HOST`. Run `julius telemetry enable` to re-enable a previously disabled installation. `DO_NOT_TRACK` and CI always disable collection and sending. Run `julius telemetry status` to inspect the current state, or `julius telemetry disable` to opt out.

Cloud workspace features require a user-configured `JULIUS_URL` with `JULIUS_CLOUD=1`, or an explicitly saved workspace connection. There is no default Julius cloud URL. Normal startup does not check npm; automatic update checks require `JULIUS_UPDATE_CHECK=1`. Explicit `julius version` and `julius upgrade` may contact npm.

Basic build and navigation run locally without model requests. Deep analysis and explicitly configured AI features can contact the model provider selected by the user.
