# Unified public repository

`Raysance/GloryBond` is the sole application source and deployment repository. Bot/Web implementation, the full README, AGENTS, functional manuals and deployment methods are maintained together. The former organization application repositories are retired archives.

The initial migration imported 509 application/Web commits and 24 earlier GloryBond commits after sanitization. A subsequent privacy cleanup removed eight historical entries whose messages referred to people, nicknames, name initials or character names. The current baseline retains 501 application/Web entries and 24 earlier public entries, plus the consolidation and privacy-cleanup commits.

Every retained historical message and file snapshot was verified byte-for-byte. Parent links reconnect around removed entries, retaining the existing application implementation. Private backups contain the original audit records outside the repository. Neither names nor the removed commit list are republished here.

Current mappings are [application history](history-map-application.txt) and [earlier public history](history-map-public.txt). Removed entries are omitted. Local Codex checkpoints and stash refs remain private work state and are not imported. Future commit messages use general functional descriptions without personal names, nicknames or name initials.

Fixed private dependencies:

- `vendor/hok-player-client`: `d9b32f1dcba5cd0e0af1b97d84c083ff774028df` (version `0.7.3`, ten commits after the `v0.7.3` tag)
- `vendor/hok-camp-client`: `8abb729ef2a5de2b288e987539040cb838aa18b2`
- `vendor/react-agent-runtime`: `d49b40745a57eeaac9ad63ab6d81d6f7ac2df406`

The player client update makes DATA sequence selection and frame writing atomic with automatic heartbeat sends. Public interfaces remain compatible. Research tools, native fixtures and historical release artifacts are now maintained outside the SDK runtime repository; application page tests use synthetic inputs rather than importing those fixtures. The reported server control codes 7/14 still have no confirmed cause.

The SDK also decodes the complete 1042 login-limit notification. A zero result continues the current session; every nonzero result, including unknown codes, raises `LobbyLoginLimited`, a compatible subclass of `LobbyControl`. The SDK preserves server details and login status metadata. Host error summaries retain only numeric protocol metadata, including `limit_time` and `detail_type`; server text and payloads stay private. Forty native wire comparisons and 542 tests against both SDK source and the installed wheel passed without network access. Server restrictions remain authoritative; future APK, schema or authentication changes require fresh verification.

Official game-client requests are now disabled through the existing `PlayerClient.enabled` flag. Online queries use the original Camp path, battle collection skips the client provider, and ordinary hero commands reach the legacy handler without client supplements. Explicit client commands and official-account status, QR and polling operations stop before network access. Camp/NapCat login and saved credentials, bindings and history are retained. SDK pins remain unchanged.

Both `.env` and `config.yaml` remain only on local/production machines and are ignored. Separate SSH configuration synchronization precedes the normal GitHub Actions source deployment. See [development](DEVELOPMENT.md) and [publication boundaries](../deployment/PUBLICATION.md).

## AI chat reliability — 2026-11-02

Chat tool selection now follows the task rather than a compulsory history-search/discovery sequence. QQ, Web and legacy background tasks use the same policy; authorized search and discovery can both succeed in the first round. Discovery returns only newly needed catalogues, and one complementary history query is sufficient. Identity, authorization, disclosure and action-result checks remain independent of this planning policy.

Public group context carries the current turn, actual speaker, original requester, mention target and reply relationship separately. Member history and bot replies use independent business/state connections and one ingress-time boundary. Later history reads retain that boundary, and accepted bot replies record their acceptance time and original question. Personal history and public conversation remain separate sources.

The roster semantic relation maps tracked participants once with a grouped join, replacing a correlated scan for every participant. Application-version definitions are always compiled into read-only CTEs with isolated names, so installed older database views cannot silently retain the slow implementation. The five-second SQL limit and read-only account remain in force. Three previously timed-out query shapes completed in approximately 0.6–1.0 seconds in read-only checks; a bounded full-row comparison matched the earlier result. The final compiler also completed the representative aggregate below the existing limit.

The default assistant is more direct and analytical. Shared reasoning instructions address mechanisms, constraints, feedback and competing explanations; presentation preserves the completed analysis. Word blacklists no longer reject legitimate criticism or trigger extra presentation requests. Personal preferences, selected roles and structural/numeric/link validation remain in effect.

Validation covers 348 host regressions, 40 deployment checks, manual references, eight synthetic live-model scenarios and read-only SQL comparisons. Host regressions include tool-free conversations, first-round independent calls, idempotent disclosure, legacy task translation, multi-speaker ownership, partial-source failure, turn cutoffs, SQL identity/cardinality, generated-name collisions and the complete worker bootstrap response. Live-model checks used synthetic input and simulated business observations without sending QQ messages or creating real tasks or memories. The actual SSH worker bootstrap and health check also passed; compilation-mode startup metadata consistently reports `trusted_cte`.
