# Unified public repository

`Raysance/GloryBond` is the sole application source and deployment repository. Bot/Web implementation, the full README, AGENTS, functional manuals and deployment methods are maintained together. The former organization application repositories are retired archives.

The initial migration imported 509 application/Web commits and 24 earlier GloryBond commits after sanitization. A subsequent privacy cleanup removed eight historical entries whose messages referred to people, nicknames, name initials or character names. The current baseline retains 501 application/Web entries and 24 earlier public entries, plus the consolidation and privacy-cleanup commits.

Every retained historical message and file snapshot was verified byte-for-byte. Parent links reconnect around removed entries, retaining the existing application implementation. Private backups contain the original audit records outside the repository. Neither names nor the removed commit list are republished here.

Current mappings are [application history](history-map-application.txt) and [earlier public history](history-map-public.txt). Removed entries are omitted. Local Codex checkpoints and stash refs remain private work state and are not imported. Future commit messages use general functional descriptions without personal names, nicknames or name initials.

Fixed private dependencies:

- `vendor/hok-player-client`: `d9b32f1dcba5cd0e0af1b97d84c083ff774028df` (version `0.7.3`, ten commits after the `v0.7.3` tag)
- `vendor/hok-camp-client`: `31ca0c2dc6afe0984aa23d28fe47847e73f12777` (version `0.9.0`)
- `vendor/react-agent-runtime`: `d49b40745a57eeaac9ad63ab6d81d6f7ac2df406`

The player client update makes DATA sequence selection and frame writing atomic with automatic heartbeat sends. Public interfaces remain compatible. Research tools, native fixtures and historical release artifacts are now maintained outside the SDK runtime repository; application page tests use synthetic inputs rather than importing those fixtures. The reported server control codes 7/14 still have no confirmed cause.

The SDK also decodes the complete 1042 login-limit notification. A zero result continues the current session; every nonzero result, including unknown codes, raises `LobbyLoginLimited`, a compatible subclass of `LobbyControl`. The SDK preserves server details and login status metadata. Host error summaries retain only numeric protocol metadata, including `limit_time` and `detail_type`; server text and payloads stay private. Forty native wire comparisons and 542 tests against both SDK source and the installed wheel passed without network access. Server restrictions remain authoritative; future APK, schema or authentication changes require fresh verification.

Official game-client requests are now disabled through the existing `PlayerClient.enabled` flag. Online queries use the original Camp path, battle collection skips the client provider, and ordinary hero commands reach the legacy handler without client supplements. Explicit client commands and official-account status, QR and polling operations stop before network access. Camp/NapCat login and saved credentials, bindings and history are retained. SDK pins remain unchanged.

Both `.env` and `config.yaml` remain only on local/production machines and are ignored. Separate SSH configuration synchronization precedes the normal GitHub Actions source deployment. See [development](DEVELOPMENT.md) and [publication boundaries](../deployment/PUBLICATION.md).

## Add Camp friend applications and shorten request spacing — 2026-11-27

The private Camp SDK exposes `add_camp_friend(friend_user_id, content=..., remark=...)`
for one explicit Camp friend application. It preserves the server response and
does not equate an application with an accepted friendship or retry an unknown
outcome. Bot/Web and agent tools do not gain an automatic friend-request entry.

At the user's request, the shared Camp HTTP entry now spaces request starts by
at least two seconds per client instance, including battle lists, details,
pagination and friend applications. Process-local reuse and serialization remain;
independent clients do not share rate state. QR and automatic watch-heartbeat
schedules retain their existing rules.

Validation: 196 SDK offline tests, 100 host compatibility tests and 45 Web tests,
package boundaries and isolated wheel installation. Explicitly authorized live
requests confirmed successful applications and existing-friend responses.
A fixed server-side daily application quota remains unconfirmed.

## Use original tracebacks in QQ error reports — 2026-11-27

Generic QQ error details now use Python's original `traceback.format_exception`
output, including exception chains, complete stack frames and exception messages.
The previous redacted cause/location sections and credential lookup for report
redaction are removed. Operation, readable summary, timestamp and report number
still accompany the traceback, delivered as literal text to the original
conversation and administrator through the existing diagnostic flow.

Validation covers exact traceback output, long messages, native text handling,
conversation routing, throttling, cancellation and delivery recovery.

## Preserve requested dates in personal history reports — 2026-11-27

When the current day's archive was absent after midnight, a range ending today
incorrectly moved its end to the oldest configured record date. The inverted
range produced an empty merge and then raised `KeyError: map_cnt`.

Historical reports now keep the requested dates, collect available snapshots
inside that range and identify missing days or missing player records. Empty
ranges and missing single-day records return an explicit no-archive result
without merging, exporting an empty page or substituting another date. Tests
cover both range orders, missing endpoints, partial coverage and absent players.
Replaying the affected request against saved production history recovered its
26 recorded battles across three days and identified the unarchived current day.

## Clarify the automatic battle report heading — 2026-11-27

Automatic post-watch reports now start with “观战对局战绩” instead of “最后一局”.
They still identify the watched battle and reuse its existing body, link and
image. Manual player-query headings keep their current wording.

## Match signed relay identifiers in watch reports — 2026-11-27

Watch metadata and completed history can represent the same 32-bit relay server
identifier as an unsigned positive number and a signed negative number. Comparing
those strings left a completed battle pending despite an already archived report.
Completion now compares relay identifiers in a common 32-bit representation and
continues to require the same battle sequence, game server and mode. Missing,
out-of-range and genuinely different relays do not match. Detail requests use
the completed row's original representation and reuse archived battle data.

Existing confirmed tasks recover without resetting their identity or delivery
state. Synthetic regressions cover both numeric representations, invalid and
mismatched IDs, a new ongoing game and one-time recovery of persisted jobs. A
read-only comparison using the affected live history confirmed that the old
comparison failed while the corrected one selected the exact archived battle.

## Keep watch preparation responsive — 2026-11-26

Avatar loading and lineup rendering now run on a separate per-request worker.
The SDK callback returns immediately so live-ready notifications and heartbeats
can proceed within their existing deadline. The handler joins the image task
before returning, preserving lineup-before-screenshot queue order even when
capture completes first. Image failures still leave the live stream available.

Pending results explicitly identify the live-ready notification timeout, separate
from video decode failures. Diagnostics record only fixed state, timeout status,
reuse and elapsed time. Offline concurrency tests cover slow rendering, delivery
order and worker completion on capture errors.

## Optional post-watch battle reports — 2026-11-26

After a successful screenshot, the requesting viewer is asked whether to receive
that battle's final report. Only their yes/no reply in the same conversation
within two minutes is accepted. Yes creates a Redis-backed task; no or expiry
starts no history queries. Confirmed requests survive target switches and restarts.

Bounded checks run once a minute for up to two hours and require an exact match of
the watched battle's sequence, servers and mode in completed history. Missing
reference data does not fall back to the latest battle. Delivery reuses the
manual player query's single-battle formatter and text/link/image message.
Enqueueing is atomic, QQ receipts are separate and unknown sends never replay.
Changed bindings, disabled query access, hidden history and request/rendering
errors stop the task and report safely to its original conversation.

Validation passed 66 focused host tests, manual/source checks and a plugin import
smoke check registering both the reply matcher and scheduled job without startup
or live requests.

## Preserve the original watch lineup template — 2026-11-26

Watch lineups now use the strength template's original font, geometry and avatar
resizing. Existing local hero artwork is preferred; all remaining images start
loading together, with a twelve-second budget and the existing cache. Response
artwork is no longer discarded solely because its CDN differs from a short list.
Red/green card shading uses a weighted comparison of available hero combat power,
match count and win rate; missing terms are omitted and the result is used only
for color, without filling missing strength or MVP figures.

## Watch lineup and retained playback — 2026-11-26

The first watch of a battle in each QQ conversation queues a lineup image before
the screenshot. It reuses the strength/prediction template and only maps data
already included in the watch response: names, heroes, avatars, hero combat power
and hero match counts. Missing metrics stay blank; no player-profile requests,
strength inference or prediction are added. Artwork uses a bounded cached loader.
Redis atomically deduplicates enqueueing for one day, separately records QQ
receipts and never retries unknown delivery outcomes.

The SDK now retains one target's watch, heartbeat and continuous decoder. Later
captures wait for a newly received frame instead of reopening the stream. End,
error, target change, credential change and shutdown close it; overlapping
captures fail immediately. Switching players replaces the retained stream. The
first frame may still show loading or accelerated catch-up.

Validation passed 184 SDK tests, 88 host integration/rendering/queue tests,
45 Web tests and 40 deployment checks, plus package, repository and manual
checks. New behavior was tested offline; no real Camp requests or QQ messages
were sent. Dependencies are delivered by commits and fixed gitlinks, without a
GitHub Release.

## Single Python version for Camp CI — 2026-11-26

The application and Camp SDK use Python 3.13, matching the production runtime.
Camp CI now has one test job with the video extra; offline tests, repository
checks and package builds each run once. Application deployment verification
also uses Python 3.13. Python 3.10/3.12 compatibility jobs are removed.

SDK updates are delivered through private repository commits and fixed
submodule references. Routine updates no longer create GitHub Releases or
upload distribution attachments; package builds remain an installation and
content-boundary check.

Python 3.13 validation passed 162 SDK tests (including video decoding), 62 host
Camp tests, 45 Web tests and 45 publication/deployment tests, plus repository,
manual and installed-wheel checks. The existing local debugger environment was
updated to the same Python minor version.

## Application source layout — 2026-11-26

Application code now lives under `src/glorybond`, grouped into QQ/Web/local
console entry points, business features, shared agent capabilities, accounts,
integrations, storage, rendering and configuration. Private SDKs retain their
public import names through exact links under `src`; their implementations remain
in private submodules. Tests, development tools, manuals and reference resources
are kept outside the application package. See [architecture](ARCHITECTURE.md).

Imports, subprocess entries, templates, handbook source indexes, packaging and
deployment checks were migrated together. The managed Web unit changes to
`python -m glorybond.apps.web`; migration preserves its user, environment file,
port and other host settings and saves the previous unit before replacement.
QQ commands, Web URLs, database/Redis schemas, private configuration, login
sessions and runtime data retain their existing behavior and locations.

Validation covers 1,283 host tests including Web and source-layout migration,
deployment/publication checks, frontend scripts, all 114 handbook source
locations, package imports and NoneBot plugin registration without startup hooks.

## Native Bilibili video delivery — 2026-11-26

Current-message video URLs, BV/av IDs and native JSON/XML share cards now use the
pinned Parser Lite standalone dependency to download and send native QQ video.
UP subscriptions and latest-video queries use the same path without cover/link
cards. The adapter loads only Bilibili stream and download interfaces; it does
not register the upstream plugin's matchers, live tasks or other platforms.

Private completed-file caching, bounded subprocess downloads and process-group
timeouts keep partial files out of delivery. Short links are constrained to
Bilibili hosts, quoted/forwarded contents do not trigger downloads, and existing
disable/sleep/maintenance checks still apply. Failed downloads or rejected queue
writes leave subscription items pending; queued messages retain the existing
receipt/no-replay behavior. Video titles remain available to content-based
automation rules without adding a separate visible card.

Delivery defaults to 480p with a 20 decimal MB limit per video. Compatible
low-resolution sources below that limit are reused directly. When compression
is needed, FFmpeg targets about 10 MB per five minutes, bounded by the per-video
limit, and preserves H.264/AAC audio and video. Exceeding the soft target alone
does not cause another encode or rejection. The final byte count is checked
before enqueueing, and cache keys include the delivery profile.

Validation covered routing, video-only output, cache reuse, duplicate shares,
failed subscription delivery, automation, sender recovery and deployment checks.
A real public video downloaded successfully and contained H.264 video and AAC
audio tracks. No synthetic test video was sent to a QQ group.

## Camp battle trends and replay reports — 2026-11-26

Camp SDK 0.8.0 adds separate winning-trend, economy/experience and full replay
report queries. Reports preserve the server's complete data, including available
player positions, combat/objective/equipment events and team economy samples.
The full report uses the player identifier from the selected battle detail.
Requests retain shared session handling, five-second spacing and no automatic
retries. Existing Bot/Web entry points do not issue these new queries implicitly.

The update also includes upstream 0.7.0's on-demand battle history pagination.
SDK validation passed 162 offline tests, package-content checks and seven query
tests against the installed wheel. Host compatibility passed 62 Camp-related
tests and 45 Web tests. New report fields were traced through the APK and official
public scripts without executing them; no live account request verified current
report availability, retention or permissions. See [Camp integration](camp-sdk.md).

## Shared Camp SDK integration — 2026-11-24

Bot and Web now delegate Camp queries through one reusable client per process.
Login adapters use public SDK methods for QR transport, roles and session export.
The private SDK owns endpoints, request fields, crypto and response parsing;
duplicate host implementations have been removed. Existing commands, page entry
points, credential storage and account authorization stay compatible. Requests
start at least five seconds apart per client, and failures are not retried
automatically. See [Camp integration](camp-sdk.md) for the host API mapping.

Offline compatibility fixtures now use synthetic renderer backgrounds and the
configured example account key. The partial-output failover test allows enough
time for its first visible chunk; the separate first-token deadline check keeps
its short timeout. The search configuration hint once again names its required
environment variable without including a credential value.

Validation passed 1,192 host tests and 45 Web tests with the fixed SDK revision.
All checks used offline fixtures and mocks, without additional Camp requests.

## Current X website subscription protocol — 2026-11-24

The X reader now discovers the x-web entry modules, transaction byte indices and
Relay query IDs from current public scripts without executing downloaded code.
It supports original and reply-inclusive timelines, current post fields and
reply pagination while retaining the legacy website path. Stable subscription
IDs resolve the current profile name through a constrained redirect; original
author checks and incremental cursor protection remain in place. Public script
caching is bounded and excludes authenticated pages and API responses.

Network, timeout and website adaptation errors now have separate credential-free
diagnostics. Missing recognized tweet results abort the batch instead of being
silently skipped. README, project conventions and subscription manuals were
updated together. Validation passed 81 host regression checks and the manual
validator. Read-only production-network checks covered account lookup, two
original-timeline pages, the reply-inclusive timeline, and two reply pages; no
test message or subscription/cursor write was performed.

## Structured foreground chat context — 2026-11-16

QQ and local Web now assemble foreground input through one host-side state/model
adapter. The current question, quote authorship and media stay together. History
is selected as complete turns with separate budgets, and identified public copies
are deduplicated without replacing detailed personal answers. Third-party quotes
follow explicit message relationships; unrelated posts from the same author do
not establish a shared topic. Subsequent questions retain the quote and answer.
An optional read-only direct-history tool retrieves omitted tasks and formats
from the trusted current session, without accepting another user or session ID.

Reference records and personal facts are projected for the current input. Stable
instructions and role presentation were shortened. The main model owns the full
answer; short answers skip presentation generation, and longer answers only get
a brief version. Presentation cannot rewrite the detailed answer. New history
retains source IDs, times and quote input, with compatible reads of older records.
Archives, authorization, background scheduling and private runtime pins remain
unchanged. Context diagnostics distinguish estimated text budgets from reported
provider usage; tool rounds and reasoning are preserved.

Validation passed 438 final host regressions, targeted Web/trace checks, 40 deployment
checks, five history-privacy checks and manual validation. Six real scenarios
were replayed, including a four-step recognition conversation with successive
generated answers carried forward. The original drift case was repeated: the
final inputs stayed on the quoted image rather than unrelated game history.
Its first input fell from 14,628 to 4,864 reported prompt tokens. Recorded tool
observations were reused; no QQ test messages, task operations or personal-state
writes were performed. Visual character identification remains unreliable; these
bounded replays do not establish a general understanding or accuracy benchmark.

## Failed task details in QQ forwards — 2026-11-12

Failed AI runs now use the existing detailed-forward and brief-message delivery
path. The forward keeps the original question, existing artifacts and trace link,
and replaces the detailed answer with a deterministic summary of recorded error
type, message, stage, elapsed time and run ID. Empty timeout messages have a
readable fallback, and error summaries reuse credential redaction. No additional
model call, retry or task replay is introduced. Original events and previously
sent partial output remain in the trace; failures do not become successful
direct-history answers. Trace durations also use recorded timestamps when failed
runs have no completed-duration field.

Validation passed 141 related host checks, 40 deployment checks, five history
privacy checks and full manual validation. A captured replay of the actual failed
run now produces the original question and a timeout summary with its recorded
120.3-second elapsed time; it sends no QQ message and makes no model request.

## Conversational intent and ordered delivery — 2026-11-12

Repeated production-context replays still turned teasing into self-deprecation,
capability defenses and literal feasibility checks. Application instructions now
scope causal analysis and capability guidance to serious information requests,
leaving social replies to respond to the current conversational intent. Role
examples emphasize familiar, light exchanges without replacing the character's
background, saved custom roles or user preferences.

The existing delivery call completes or retains the full response before deriving
its short version; examples generate `detailed` before `chat`, while parsing stays
compatible with earlier field orders. A social draft's unhelpful rhetorical route
can be replaced as a whole, rather than preserving a defense in softer wording.
Facts, complete requested works, numeric/source checks and real execution status
retain their existing boundaries. Already suitable reports and works can keep
`detailed=null`, avoiding an unnecessary second copy of the full text.

Per-message historical-assistant annotations are shorter. Complete saved replies,
authors and protocol fields remain intact, and unverified old claims still cannot
serve as current evidence. The shared system policy defines the source boundary
and makes clear that old self-narratives and speaking habits need not continue.
No archive, role selection, personal preference or memory is deleted or rewritten.

Validation includes repeated original-context replays, a separate serious-query
control, verbatim-output and numeric/source-preservation controls, host and
deployment regressions, privacy checks and manual validation. Every replay sample
and repair remains in private diagnostics; no QQ test messages or user-state writes
are performed. A separate Doubao text trial did not establish a stable advantage,
so the text route remains DeepSeek Flash and the independent vision route is
unchanged. These are bounded style checks, not a general intelligence benchmark.

## Independent Doubao vision routing — 2026-11-11

QQ and local Web can route image-bearing requests through a shared `VisionAPI`
with its own endpoint, named environment key, proxy and timeouts. The chosen
model is `doubao-seed-2-1-lite-260915`. Text generation, reply composition and
text failover retain their existing channel settings. Routing happens after
attachment resolution and image-budget omission, including historical images and
images supplied by tools. Ark image detail conversion affects only the request
snapshot; existing conversation data and source pixels are preserved.
Streaming encrypted thinking is retained verbatim through tool rounds, as required
by Seed 2.1. Provider-specific ciphertext is omitted only from outgoing requests
to other providers, leaving the saved messages intact.

The worker exposes the vision key only in private settings and registers it for
redaction. Vision failures retain their actual status and cannot trigger text
failover. Offline checks cover routing, history, tools, provider-specific payloads,
proxy and credential separation, metadata, legacy behavior and worker bootstrap.
Initial validation passed 131 related Python checks, eight image UI checks and full
manual validation (102 nodes, 33 documents, 111 source locations). Model activation
subsequently enabled both existing Ark keys. A live synthetic image test counted
three red squares, called a multiplication tool and returned six; the second
request retained the encrypted thinking from the tool-call response. The server
key also passed an image request. Only `VisionAPI` was added under the credentials
lock, with a private configuration backup and existing credentials and other
settings preserved. This confirms API wiring, not comparative recognition accuracy.
API Key creation and activation instructions are documented in the
[adapter guide](../src/glorybond/agent/README.md#豆包识图接入).

## Conversational judgment and social response — 2026-11-11

A review of 35 recent production conversations, with ten complete private runs
retained for diagnosis, found repeated self-deprecation, capability defenses and
literal treatment of jokes. Shared interaction goals now emphasize independent
judgment, contextual humor and conversational implication across the default
assistant and selected roles. They distinguish correcting a specific mistake
from repeatedly grading or defending the bot's own performance. Built-in voice
cards no longer make self-deprecation the standard response to teasing.
Persona assembly also distinguishes conversational role lines and playful
hypotheticals from factual claims and actual actions, retaining trusted identity,
authorization and execution checks for the latter.

The existing delivery editor preserves useful observations and the force of an
answer while editing both detailed and short variants. It can change the rhetorical
angle without inventing facts, actions or personal motives. Full artifacts,
numeric/source checks and detailed direct history retain their existing contracts.
Validation passed 178 related host checks, 40 deployment/startup checks, five
history-privacy checks and full manual validation. It also combines paired
production-context replays and synthetic multi-turn probes using both the default
assistant and a saved custom role. Replays send no QQ messages and do not write
tasks, role selections or personal memories. Dense old self-narratives remain a
harder case than fresh conversations; these checks do not establish a general
intelligence or recognition-accuracy improvement.

## Host security maintenance — 2026-11-05

Host maintenance now has guarded vendor updates, private restore points, service health checks and separate overnight update/reboot windows. Alibaba Cloud Linux system packages stay on official distribution repositories; Nginx uses official stable RPMs, PostgreSQL stays on major 16, and the standalone website Node runtime stays on major 22. Failed or incomplete transactions block unattended reboot. Application deployment remains separate. See [operations](../deployment/server_modules/SECURITY_UPDATES.md).

The current operator preference pauses the daily update and reboot timers, together with DNF metadata prefetch. Updates are checked and applied manually through the existing guarded entry point; boot-time service verification remains enabled. Operations documentation also distinguishes rebuildable caches and inactive editor binaries from persistent data, editing history, diagnostic logs and restore points.

The mandatory pre-commit SDK refresh advances the Camp client to its current main commit. It adds optional targeted spectating APIs while retaining the login and saved-session interfaces used by the host; this maintenance change does not invoke the new APIs.

## Poke emoji template recovery — 2026-11-03

The default emoji template directory contained only its README and placeholder, so the image branch of group pokes raised `emoji_template_error: no templates found in template dirs`. The three documented reference images were recovered byte-for-byte from their existing public reference copies, visually inspected and restored as tracked application resources. Their provenance remains in the template README; generated images, custom uploads and unrelated cached references are not included.

Publication verification now requires all three images in the actual staged tree, preventing a deployment with documentation but no default templates. A specific missing-template exception lets group pokes fall back to the existing text reply without starting image generation. Other generation failures keep their existing diagnostics. Default random selection still excludes extra resource directories, while explicit template selection and user-provided references remain supported.

Validation covers 14 host checks for decoding the bundled originals, prefix/name selection, legacy resource paths outside the project working directory, selection scope, generation short-circuiting, poke fallback and existing command/context behavior; five publication/privacy checks; 40 deployment checks; and full manual validation. The recovered files match the source copies' SHA-256 hashes. No QQ test messages or paid image-generation requests were sent.

## Conversational judgment — 2026-11-03

The shared expression policy now directs the default assistant's bluntness toward core mechanisms and consequential errors. Casual recognition, jokes and aesthetic discussion stay conversational; once the user accepts an approximate interpretation, the assistant continues without repeatedly demanding provenance or appending verification disclaimers. Explicit source checks, important decisions and action parameters retain their necessary checks. The same policy reaches the main answer, partial messages and short presentation through the existing shared entry points, without an additional classifier or review request.

The built-in assistant profile, voice and examples follow the same goal. Its analytical example no longer invents a history of repeated user mistakes. The memory policy explicitly scopes external-fact verification to persistence, keeping that constraint from becoming a demand to authenticate every casual remark. Documentation and existing role-selection tests were synchronized.

Validation: 141 related host regressions, 40 deployment checks, four history-privacy checks, and manual validation covering 102 nodes, 33 documents and 111 source locations. Eight synthetic live-model scenarios exercised both the main answer and short presentation, including continuation after a stubborn historical reply, casual recognition, jokes, approximate comparisons, explicit provenance checks, causal analysis and truthful send/memory reporting. Two additional runs used the previous policy as controls. These are text conversation checks, not image-recognition accuracy measurements; no QQ messages or persistent personal memories were created.

### Role interaction and delivery editing follow-up

Production conversations in role mode still defended earlier replies, treated teasing as a factual dispute, and attributed the robot's behavior to group members. The shared goal now explicitly treats users as conversation partners; role self-respect and banter do not require maintaining earlier positions. The built-in analytical role's profile and voice follow that goal. Personal and public history retain their original content while marking earlier self-narratives and interpersonal attributions as generated claims rather than lived experience.

The existing presentation call can now supply an edited `detailed` answer as well as `chat`. It removes rhetorical self-defense, unsupported personal attributions and irrelevant disclaimers without another model call or investigation. Brief social exchanges can use the same concise response in both versions; factual explanations, quoted material and requested artifacts retain their complete delivery. The edited full answer is saved in direct dialogue, while raw ReAct output and provider payloads remain in run records. Legacy responses without the new field remain supported. Edited details must retain the original numeric-value and HTTP-source-link sets and stay within the source budget; these checks constrain literals, not semantic equivalence. Existing repair limits and fallback behavior remain in effect.

Validation includes 158 host regressions, 40 deployment checks, four history-privacy checks and full manual validation. Production inputs were replayed with their selected role, full direct history, public background and explicit quote; two complete pipeline replays and four repeated presentation replays checked both delivered variants. Additional synthetic checks covered the default assistant, a custom role, explicit provenance, causal analysis and unconfirmed send status. Tools and persistent mutations were not executed during replay. Diagnostic runs showed why prompt-only changes and short-version checks were insufficient; verification now inspects the edited detailed answer and saved dialogue as well.

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

## Live screenshots and SDK-owned Camp sessions — 2026-11-25

`#观战昵称`, `#观战我` and `#我的观战` resolve the existing player directory, report progress, then return one JPEG from the SDK live stream. Concurrent capture requests stop immediately; unavailable targets, timeouts and errors do not retry. The stream and reader close after capture. Existing prediction and legacy observation commands remain available.

Camp credentials are no longer read or projected by Bot/Web/login adapters. The SDK owns the private session file, preserves request pacing across reloads, and atomically publishes verified account switches with revision checks. Deployment delegates one-time offline import of the existing dotenv session to the private SDK tool without replacing a newer file. The host adds the video decoder dependency; no real watch or QQ-message test is performed during this integration.

Validation passed 93 host checks, 45 Web checks and 46 deployment/readiness checks, plus the complete manual validator. SDK validation passed 143 tests and the Python 3.10/3.12/3.13 CI jobs; its private release includes wheel, sdist and checksums.
