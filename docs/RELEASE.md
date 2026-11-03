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

## Conversational judgment — 2026-11-03

The shared expression policy now directs the default assistant's bluntness toward core mechanisms and consequential errors. Casual recognition, jokes and aesthetic discussion stay conversational; once the user accepts an approximate interpretation, the assistant continues without repeatedly demanding provenance or appending verification disclaimers. Explicit source checks, important decisions and action parameters retain their necessary checks. The same policy reaches the main answer, partial messages and short presentation through the existing shared entry points, without an additional classifier or review request.

The built-in assistant profile, voice and examples follow the same goal. Its analytical example no longer invents a history of repeated user mistakes. The memory policy explicitly scopes external-fact verification to persistence, keeping that constraint from becoming a demand to authenticate every casual remark. Documentation and existing role-selection tests were synchronized.

Validation: 141 related host regressions, 40 deployment checks, four history-privacy checks, and manual validation covering 102 nodes, 33 documents and 111 source locations. Eight synthetic live-model scenarios exercised both the main answer and short presentation, including continuation after a stubborn historical reply, casual recognition, jokes, approximate comparisons, explicit provenance checks, causal analysis and truthful send/memory reporting. Two additional runs used the previous policy as controls. These are text conversation checks, not image-recognition accuracy measurements; no QQ messages or persistent personal memories were created.

## AI chat reliability — 2026-11-02

Chat tool selection now follows the task rather than a compulsory history-search/discovery sequence. QQ, Web and legacy background tasks use the same policy; authorized search and discovery can both succeed in the first round. Discovery returns only newly needed catalogues, and one complementary history query is sufficient. Identity, authorization, disclosure and action-result checks remain independent of this planning policy.

Public group context carries the current turn, actual speaker, original requester, mention target and reply relationship separately. Member history and bot replies use independent business/state connections and one ingress-time boundary. Later history reads retain that boundary, and accepted bot replies record their acceptance time and original question. Personal history and public conversation remain separate sources.

The roster semantic relation maps tracked participants once with a grouped join, replacing a correlated scan for every participant. Application-version definitions are always compiled into read-only CTEs with isolated names, so installed older database views cannot silently retain the slow implementation. The five-second SQL limit and read-only account remain in force. Three previously timed-out query shapes completed in approximately 0.6–1.0 seconds in read-only checks; a bounded full-row comparison matched the earlier result. The final compiler also completed the representative aggregate below the existing limit.

The default assistant is more direct and analytical. Shared reasoning instructions address mechanisms, constraints, feedback and competing explanations; presentation preserves the completed analysis. Word blacklists no longer reject legitimate criticism or trigger extra presentation requests. Personal preferences, selected roles and structural/numeric/link validation remain in effect.

Validation covers 348 host regressions, 40 deployment checks, manual references, eight synthetic live-model scenarios and read-only SQL comparisons. Host regressions include tool-free conversations, first-round independent calls, idempotent disclosure, legacy task translation, multi-speaker ownership, partial-source failure, turn cutoffs, SQL identity/cardinality, generated-name collisions and the complete worker bootstrap response. Live-model checks used synthetic input and simulated business observations without sending QQ messages or creating real tasks or memories. The actual SSH worker bootstrap and health check also passed; compilation-mode startup metadata consistently reports `trusted_cte`.

### Continuous-task follow-up

Recent real conversations exposed a gap in those smoke checks: a completed run could contain an unexecuted query promise, lose the requested deliverable, or inherit an earlier assistant's incorrect capability claim. Discovery now advertises authorized tool names, purposes and effects before loading their parameters. QQ retains the detailed answer in personal dialogue instead of the lossy short version; public group background still contains only accepted short replies. Execution instructions follow role/background data and keep the requested deliverable, subject and scope throughout retrieval. Creative framing is distinguished from factual claims, and presentation preserves representative content from the requested artifact.

DeepSeek reasoning is no longer disabled simply because a request contains tools. Automatic selection preserves reasoning; forced/named selection uses the protocol-supported non-thinking mode, and existing reasoning fields survive subsequent tool requests. This follows the official [thinking-mode guide](https://api-docs.deepseek.com/guides/thinking_mode/) and [tool-choice contract](https://api-docs.deepseek.com/api/create-chat-completion/). The existing QQ thinking setting is enabled without changing other private configuration. Presentation follows the same channel setting for selection/editing, while retaining its no-tools, no-new-calculations contract. It adds reasoning work rather than another classification or review request.

The game semantic layer provides nullable `is_mvp` columns for player and roster rows, normalizing boolean/0/1 source representations while preserving unknown values. Model SQL no longer needs to cast JSON "false" text to an integer. SQL observations also state their archive coverage explicitly: absent records or the last recorded date do not prove that real activity stopped. Validation includes 353 host regressions, 40 deployment checks, privacy/manual checks, and replay of recent failed inputs with their existing history against the real model and read-only worker. Replay outputs are captured in memory, without sending QQ messages, creating tasks or changing personal memories.


### Evidence and analytical scope follow-up

Historical chat review exposed identity guesses, unsupported memory expansion, calendar/business-date confusion, mismatched analytical cohorts, and schedule-based delivery assumptions. Reference lookup now distinguishes exact matches, candidates, ambiguity and absence. New personal-memory writes require literal evidence from the current input; summaries and source quotations remain distinct through storage and persona assembly. Background tasks cannot automatically write new personal facts. Prior assistant answers retain their full text with an explicit source boundary, so earlier unsupported figures or capability claims do not become fresh evidence. One confirmed erroneous historical memory attribution was removed with a compare-and-set update while preserving unrelated content.

Game analysis accepts one shared scope for battle, equipment and roster relations. The trusted compiler applies mode and time filters before aggregation, defaults to official games and calendar time, and bounds reads by the trusted ingress clock. Calendar queries reject archival-day filtering; explicit business-day analysis remains supported. Observations include decimal totals of returned numeric columns with completeness markers, without inferring business denominators or adding averages. PostgreSQL string aggregation also accepts the parser's canonical function representation.

Tasks persist claim, start and finish evidence separately from QQ send receipts. Completed attempts and scheduled times do not establish delivery; absent evidence remains unverified. Private sends to the caller bind the recipient at the entry point. Notification writes explicitly distinguish all matching messages from content-limited triggers; content-limited rules cannot be saved without content conditions, and unspecified cooldowns retain defaults. Existing notification rules retain their saved definitions and creator-only management.

Validation: 433 host regressions, 40 deployment checks, four history-privacy checks, and manual routing/source validation. Nine historical foreground inputs were replayed against the real configured model with prior dialogue, followed by targeted replays after source-boundary changes. Actual read-only PostgreSQL and sandbox plotting confirmed calendar-month games across midnight and produced the requested two charts; task snapshots and message/memory/rule mutations were simulated, without sending QQ test messages or creating real tasks or rules. Pure role-tone preferences remain unchanged.


### One-day temporary web links

Temporary battle, query, video-redirect and chat-trace links now share `Redis.REDIS_TEXT_EXPIRE_SECONDS=86400`. Chat traces and their discovery index use the same setting rather than a separate seven-day override. The local and deployed private configuration were updated without changing other configuration values. Reads do not renew a link.

The file-backed benefit page enforces the same lifetime against the generated JSON timestamp, returns 410 when missing or expired, and uses the supported keyword template interface. Its responses remain uncached by the browser. Existing trace deadlines and cached-link TTLs are normalized without extending shorter remaining lifetimes; source archives, private JSONL and the physical file-cleanup schedule are retained. Validation covers the one-day Redis lifetime, non-renewing reads, file-link boundary and 42 Web regressions.
