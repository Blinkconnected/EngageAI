# The connector framework

> **Status: the SDK is frozen.**
>
> The six surfaces below — manifest, validation, diagnostics, repair,
> certification and the test suite — are the contract a connector implements,
> and they change only for a critical architectural reason. New work extends
> the SDK by adding *connectors*, not by changing it.
>
> The reason for freezing here rather than earlier: the contract was wrong
> three separate times, and each time it was four independent implementations
> hitting the *same* gap that proved it. That signal stopped. The last two
> additions — lifecycle and certification — needed no contract change from
> the connectors' side, which is the real test of whether an abstraction is
> finished.
>
> Changing it now means changing every connector, including ones written
> outside this repository. See **Extending, not changing** at the end.

Blink Engage is a messaging platform. A channel is a transport adapter.

That is a product principle, and this is where it stops being a slogan: a
**capability contract** every connector answers, and a connection flow
*derived* from the answers. The wizard that connects WhatsApp is the same
wizard, running the same code, that connects Telegram — and that will connect
Slack, Teams, RCS, LINE or WeChat.

## The manifest

`domain/connector_manifest.py`. A connector does not *implement* a wizard, it
**describes itself**, and the wizard renders the description.

| Field | What the console does with it |
|---|---|
| `name_key`, `description_key`, `icon`, `category` | Draws the picker entry |
| `capabilities` | Derives the flow |
| `auth_methods` | Offers consent, a form, or both |
| `required_permissions` | Shows what is about to be approved |
| `required_credentials` | Renders the form, field by field |
| `required_resources` | Titles the picker, and explains an empty one |
| `verification_steps` | Draws the checklist *before* it has answers |
| `repair_actions` | Renders the repair buttons |
| `supported_features` | Says what the channel can carry, before connecting |
| `documentation` | The last resort, for a customer genuinely stuck |
| `minimum_platform_version` | Refuses a connector shipped ahead of its platform |

Static, credential-free, serialisable whole — which is what makes the wizard a
renderer rather than a participant. Served on `GET /channel-connect/catalog`.

**The console never infers.** Anything it had to work out for itself becomes a
lookup table keyed by channel, which is the hardcoding the manifest replaces.

### Validation returns codes, not strings

`ValidationCode` is a **closed set**. Two reasons pulling the same way: the
console translates a code, so an Arabic customer reads Arabic — where a
sentence from the server could only ever be English. And a closed set means
every failure a connector can report is one somebody has written copy for.

Whether a code blocks is decided **centrally**, in `BLOCKING_CODES`, so one
channel cannot stop a customer for something another waves through. Four codes
are deliberately non-blocking and each says why in the test that asserts it:
`PROVIDER_UNREACHABLE` and `RATE_LIMITED` are somebody else's outage, and
`WEBHOOK_NOT_REGISTERED` is always true during setup and about to stop being.

A connector may only return codes its manifest declared —
`test_connector_manifests.py` reads the source and holds it to that, because
an undeclared code is a raw slug in front of a customer at the worst moment.

### Repairs are declared, not discovered

A `RepairAction` carries its title, description, whether to confirm, the
permission it needs and whether it can run before a channel exists. One
endpoint serves all of them:

```
POST /channel-connect/channels/{id}/repair/{action_id}
```

The action is checked against the manifest before anything runs, so the set of
things that can be invoked is exactly the set advertised. A connector adding
"refresh token" adds a `RepairAction` and a branch in its own `repair`; the
console grows a button and the API does not change.

## Lifecycle: two axes, one badge

The eight states a customer sees come from two independent facts, and keeping
them apart is what makes the answer correct on every installation.

| Axis | Values | Owner | Lifetime |
|---|---|---|---|
| **Maturity** | preview, beta, production, deprecated, end of life | The connector author | Ships with the code, identical everywhere |
| **Availability** | available, maintenance, disabled | Whoever runs the installation | Runtime, different per deployment |

`effective_state()` resolves them into the single badge the console draws.
**Availability wins whenever it says anything** — "we have turned this off" is
more urgent and more actionable than "this code is mature", and showing a
maturity badge on a connector nobody can use answers a question the customer
did not ask.

Collapsing the two would mean a connector in maintenance forgets it is
production-grade, and a deprecated one cannot be paused without losing the
deprecation.

**Existing channels are never withdrawn by a status change.** Disabled,
maintenance and end-of-life refuse a *new* connection and leave running
channels alone. Taking a channel away from a customer who is receiving
messages on it is a decision an operator makes explicitly.

Preview, beta and deprecated warn without blocking — blocking would make
Preview useless as a release stage, and a customer may connect something
unfinished as long as they were told.

## Versioning

Three versions people routinely conflate, so the manifest names each:

| Field | What it is |
|---|---|
| `connector` | The connector's **own** code |
| `api` | The **provider's** API this connector talks to — `v21.0`, `2010-04-01`, or nothing |
| `minimum_platform` | The oldest Blink Engage it runs on |

A connector requiring a newer platform is **not offered**, with its own
reason — so an administrator learns they need to upgrade before a customer
meets a flow that cannot finish.

Pre-release suffixes are parsed and ignored when comparing. Blink Engage is
`1.0.0-beta.5`; if that did not satisfy `1.0.0`, no connector could declare a
minimum until the first stable release and the field would mean nothing. An
*unparseable* version on either side answers "supported" — a connector that
vanished because somebody's build stamped a non-semver string is a worse
failure than one that appears and is never used.

`api` is deliberately free text. Providers version themselves however they
like, and Telegram's Bot API states no version at all — the connector reports
`unversioned` rather than inventing one, because an invented version
manufactures exactly the deprecation risk the field exists to communicate.

## The feature matrix

`ChannelFeature` is a closed set, and every entry carries a **direction**.

That second part is what makes the matrix honest. SMS receives media and
cannot send it — `SmsProvider.send_message` raises on an outbound
attachment — so one tick against "Media" would be wrong whichever way the
reader assumed. It is declared `inbound`.

Free strings were the previous version, and they were a matrix that lied: one
connector said `"images"` and another `"media"`, so nothing could be compared.

Real differences the matrix now carries correctly:

- WhatsApp does **not** claim typing indicators — its `typing_indicator` is a
  documented no-op — while Messenger and Instagram genuinely send
  `sender_action`.
- Telegram and WhatsApp declare threading **inbound only**: the outbound half
  is unreachable, because `ConversationService.send_reply` populates a reply
  reference only for a provider declaring
  `supports_invisible_reply_threading`, and Email is the only one that does.
  The reply code in those providers is real and never called, so `both` would
  promise a quoted reply the product cannot send.
- Nothing claims voice or video, because nothing implements them. A test
  asserts it — that would be the most visible possible overclaim.

## Diagnostics

`GET /channel-connect/channels/{id}/diagnostics`. Built for a support engineer
with a customer on the phone: the answer to "why is this not working" without
a database query, a log search and a guess.

Two contributors, merged, with the connector winning any key both can answer —
a real measurement beats a remembered one:

- **The connector** asks the provider what only it can know: does the token
  still work, is the webhook registered *at the provider*, which scopes are
  granted, how much rate-limit headroom is left.
- **The platform** reads what it already recorded: the last health check, the
  connection log, when something last succeeded and last failed. No connector
  implements any of it, so every channel has a useful report from the day it
  is written.

**Every key is always present.** Anything nobody measured comes back
`unknown` rather than absent — a missing row and a row saying "not measured"
look identical in a screenshot and mean completely different things.

### The rule that matters: never invent an OK

A green tick on something nobody measured sends an engineer away from the
actual problem with more confidence than they started with. Three cases where
that nearly shipped, each now pinned by a test:

- Email reported `webhook_status: ok` from `bool(imap_host)` alone. A host
  configured with a blank password would have shown green on the one row read
  as "is anything arriving?" while nothing arrived.
- Meta classified *any* Graph error envelope as a rejected credential —
  including throttling, which arrives in the same shape. That sends an
  engineer to rotate a working token during an outage.
- A Graph timestamp too large for the platform clock raised outside the
  caller's guard and silently discarded the connector's entire half of the
  report, leaving four rows blank.

A connector answers only what it can measure; `UNKNOWN` is a first-class
answer and `complete()` fills the rest.

## The rule

**Nothing above the connector layer may branch on a channel type.**

No `if channel == "whatsapp"`, in the wizard service, in the API, or in the
console. A screen that asks *which channel is this?* has to be changed for
every channel added after it. A screen that asks *what can this connector do?*
does not.

Adding a channel is one file in `infrastructure/connectors/` and one line in
that package's `__init__`. If it is ever more than that, the abstraction has
broken and the fix belongs in the contract, not in the caller.

## Two contracts, deliberately

| | `ChannelProvider` | `Connector` |
|---|---|---|
| Answers | How do I talk to this channel? | How does a customer connect it? |
| Lives in | `domain/channel_provider.py` | `domain/connector.py` |
| Built | Per message, with decrypted credentials | Once, as a singleton |
| Knows | send, receive, upload, health | capabilities, auth, discovery, checks |

Merging them would put OAuth machinery in the hot path of every outbound
message, and would mean a channel could not be *connected* without
instantiating its *transport*.

## Capabilities

`domain/connectors.py`. A frozen set rather than a record of booleans, so
adding one does not mean editing every connector that will never have it.

| Capability | Means |
|---|---|
| `OAUTH` | The customer consents rather than pasting a secret |
| `AUTO_DISCOVERY` | We can list what they own, so they pick from a list |
| `WEBHOOKS` | The provider pushes inbound events |
| `AUTOMATIC_WEBHOOK_REGISTRATION` | *We* register the callback, not the customer |
| `SHARED_WEBHOOK` | One installation-wide callback, fanned out by payload |
| `TOKEN_REFRESH` | Credentials expire and can be renewed unattended |
| `HEALTH_CHECKS` | It can be asked, cheaply and on a timer, if it still works |
| `EMBEDDED_SIGNUP` | The customer can create the account *during* the flow |
| `MANUAL_CONFIGURATION` | Credentials can be entered by hand |

### Resolved per deployment, not declared once

The same Meta connector offers OAuth on a hosted installation holding a Meta
app, offers it on a self-hosted one whose administrator supplied their own,
and offers only the guided manual path on one with neither.

| Deployment | `configured_apps` | Meta flow |
|---|---|---|
| Hosted | `{"meta"}` | `select → oauth_redirect → resource_picker → checklist → summary` |
| Self-hosted, own app | `{"meta"}` | identical |
| Self-hosted, no app | `∅` | `select → form → checklist → summary` |

Three rows in an operator's mental model, one implementation. A capability
that is unavailable carries a **reason code** — never prose, so the console
can translate it.

**The manual path is permanent, not transitional.** It is the only path with
no provider app, the fallback when consent fails, and the one that works while
app review is pending.

## The flow is derived

`steps_for(profile)` is the load-bearing function. Every branch tests a
capability; none tests a channel.

```
                        ┌─ OAUTH ──────────→ oauth_redirect
select ─→ authenticate ─┤
                        └─ MANUAL_CONFIG ──→ form

discover   only when OAUTH *and* AUTO_DISCOVERY   → resource_picker
verify     only when HEALTH_CHECKS or WEBHOOKS    → checklist
connect    always                                 → summary
```

Discovery tests the **grant**, not only the capability: a customer who pasted
one credential has already named the resource, and a picker with one entry is
a step that exists to be clicked past.

The console switches on **`StepKind`** — six renderers — and never on the
channel. A seventh renderer would be telling us something genuinely new about
connecting to things, which is a good reason to add one deliberately and a bad
thing to discover inside a screen full of channel branches.

## What the contract had to learn

The first version was written, four connectors were built against it, and an
adversarial review found that all four had hit the *same three* gaps. That is
the signal a contract is wrong rather than its implementations — and it was
cheaper to find with four independent readings than with one.

| Gap | Why it mattered | Fix |
|---|---|---|
| `check(grant, selection)` | For a form-based connector the "grant" is just what was typed. Four connectors guessed four ways; whichever the wizard matched, three would have silently probed an empty dict. | One `Attempt` carrying `inputs`, `grant`, `selection`, `context`, `display_name` |
| Webhook registration inside `connect()` | The callback URL contains the channel id, which is assigned *after* `connect` returns. One connector invented an id and registered a URL that answered 404 forever; another refused the capability outright. | `register_webhook(callback_url=…)`, called once the row exists |
| `repair()` returning credentials | A webhook secret lives in a **column**. Returning it as a credential left the column stale and every inbound message failing signature checks — silently, because a stale secret looks exactly like a channel nobody has messaged. | A `Repair` result carrying both |
| No fix for "you typed it wrong" | Three connectors reached for `reauthorize`, which on a channel with no OAuth renders a consent button that goes nowhere. On a pasted-secret channel a mistyped credential is *the* commonest failure. | `FIX_REENTER` |

## Writing a connector

Two members are the bar: a `manifest` and `connect`.

```python
@ConnectorRegistry.register("slack")
class SlackConnector(Connector):
    app_key = "slack"

    MANIFEST = ConnectorManifest(
        channel_type="slack",
        name_key="connect.slack.name",
        description_key="connect.slack.description",
        category=ConnectorCategory.MESSAGING,
        icon="slack",
        capabilities=frozenset({Capability.OAUTH, Capability.AUTO_DISCOVERY}),
        auth_methods=(AuthMethod.OAUTH,),
        required_permissions=("channels:read", "chat:write"),
        required_resources=(ResourceSpec(...),),
        verification_steps=(VerificationSpec(...),),
        repair_actions=(RepairAction(...),),
    )

    @property
    def manifest(self): return self.MANIFEST

    async def connect(self, *, company_id, attempt): ...
```

Everything else — `authorize_url`, `discover`, `validate`, `register_webhook`,
`repair` — is optional and defaults to the honest answer. `credential_fields`
is derived from the manifest and should not be overridden: two statements of
one form is one place for them to disagree.

**Nothing in the console changes.** That is the whole claim, and
`test_connector_manifests.py` is where it is either true or it isn't — every
test there derives its expectation from the registry, so a connector added
tomorrow is covered the moment it registers.

Rules, all enforced by `tests/unit/test_channel_connectors.py`:

- **Declare only what you deliver.** A connector declaring
  `AUTOMATIC_WEBHOOK_REGISTRATION` must override `register_webhook`; one
  declaring `AUTO_DISCOVERY` must override `discover`. Derived from the
  registry, so a new connector is covered the moment it registers.
- **The credentials you return must be exactly what your `ChannelProvider`
  reads.** The highest-value test in the suite: a mismatch means the channel
  connects, reports healthy, and silently never sends.
- **Every customer-facing string is a translation key.** `CheckOutcome.code`,
  `label_key`, `help_key`, `CapabilityState.reason`, `Fix.instructions_key`.
  Prose from the server can never be Arabic.
- **Every network call carries a timeout**, and nothing that escapes may
  contain a token — `error_sanitizer.redact_credentials` exists for this, and
  a bot token sits in a Telegram URL.
- **`check()` returns outcomes and never raises.** Transport failures
  included: a check that raised would collapse five findings into whichever
  was evaluated first, in the one step whose job is explaining what is wrong.

## Inbound is already normalised

Worth stating because it is easy to assume otherwise: `receive_message`
returns `list[InboundMessage]`, and `InboundMessage` is the common internal
model. Nothing above the transport layer knows whether a message came from
Meta, Telegram or email — that has been true since the channel layer was
built.

What the shared-webhook model adds is shared **ingress**: under a provider app
whose callback is configured once, every tenant's events arrive at one URL and
are routed by the ids in the payload. `Connection.external_id` is what makes
that possible, which is why it exists.

## Not built yet

Stated so nobody looks for them:

- **The wizard service and its API.** The contract, the registry and seven
  connectors exist and are tested; the session state machine that drives a
  customer through the derived steps does not.
- **OAuth end to end.** `authorize_url` builds the dialog URL but no
  installation holds Meta credentials, and `exchange()` is unimplemented —
  `DeploymentContext` carries app *keys*, not app secrets, so redeeming a code
  needs a resolver that reads the encrypted platform settings.
- **The console.** No `connect.*` translation bundle exists yet, so the keys
  every connector emits resolve to nothing today.
- **Meta's manual path has no App Secret field**, so a hand-connected Meta
  channel gets `webhook_secret=None` and inbound signature verification fails
  silently. `Field` cannot yet say "this input lands in a column, not in
  credentials" — a contract decision, not a connector edit.

## The wizard

`application/services/channel_connect_service.py` and
`api/v1/endpoints/channel_connect.py`. Neither names a channel.

| Endpoint | Purpose |
|---|---|
| `GET /channel-connect/catalog` | What can be connected here, with capabilities and reasons |
| `POST /channel-connect/sessions` | Start, from a channel or a template |
| `GET /channel-connect/sessions/{id}` | Re-read — a refresh lands where the customer left off |
| `POST .../advance` | Answer the live step |
| `POST .../connect` | Make it real, then register the webhook |

**One `advance` endpoint for every step**, because the step decides what an
answer means. An endpoint per step kind would put the flow's shape into the
API surface, where changing a derivation becomes a breaking change.

Sessions live in Redis with a 30-minute TTL. A half-finished connection is
worth nothing an hour later — its OAuth state has expired and its discovered
resources are stale — so persisting it would mean a migration and a cleanup
job for something whose value is measured in minutes. Tenancy is read from
the session and checked on every access, never taken from a parameter: the
session id is the only thing an OAuth callback carries back.

### Order of operations on connect

1. `connector.connect()` — subscribe the app, claim the resource, return what to store
2. Write the `ChannelConfig` row — **this is where the id is assigned**
3. `connector.register_webhook(callback_url=…)` — with the real URL
4. Persist any secret the registration agreed, *before* anything verifies a
   signature against it

Step 4 is not fussiness. A webhook secret the provider has and the column does
not means every inbound message fails verification — silently, because a
channel nobody has messaged looks identical to one whose messages are all
being rejected.

### Automatic steps run on arrival

The Verify step is `automatic`. Its checks run when the customer *lands* on
it, not when they try to leave: running them on the way out would show an
empty checklist and then move past it, so the one step whose whole job is
saying what is wrong would be the one that never said anything.

## Certification

`POST /channel-connect/channels/{id}/certify` runs the connector's scenarios
against a live channel and scores what came back.

Eleven scenarios — authentication, send, receive, media up and down, read
receipt, typing indicator, webhook delivery, token refresh, disconnect,
reconnect — each returning **pass, fail, warning, skipped or not supported**,
with its own execution time and diagnostics.

### The three rules the score depends on

**Not supported does not count against you.** SMS cannot send media. Scoring
that as a failure would give every honest connector a worse score than a
dishonest one, and within a week every manifest would claim everything. The
denominator is what the connector *claimed* — which is the feature matrix
that already exists, so the scenario list is **derived from the manifest**
rather than declared a second time. Direction decides: a connector receiving
media and not sending it gets `media_download` and not `media_upload`.

**Not executed does not count for you.** Three passes out of eleven is not
100%; it is 100% of very little. Certification carries **coverage** alongside
the score, and withholds a grade below 60% coverage whatever the score says —
otherwise "96%, Production Ready" is a sentence a suite can produce by running
almost nothing.

**One failure keeps it out of production.** Nine passes and a broken
authentication is not a 90% channel, it is a channel that does not work. The
arithmetic alone would have called it production ready.

A warning is worth half a pass: it did the thing, with something worth saying.

### The score cannot be assigned

`Certification` is frozen and constructed only by `certify()`. There is no
setter, no override, and no way to certify a connector except by running it.

### Nothing messages a real customer

A certification run against a live channel is a run against somebody's
WhatsApp number. Scenarios that would put something in front of a person are
listed in `EMITS_TO_A_CUSTOMER` and are **skipped without an explicit
target** — never guessed at, never aimed at the last person who wrote in.

`MUTATES_THE_CHANNEL` — disconnect, reconnect, token refresh — is off unless
asked for by name, because a run that left a working channel in whatever
state it finished in is a diagnostic worse than the problem.

The runner enforces both, and decides applicability and timing too. **A
connector demonstrates; it never grades.** A connector deciding its own
scenario was not applicable is a connector deciding its own denominator.

### Compatibility

Platform version, connector version, provider API version, when the suite last
actually ran, and when the provider retires the API version this connector
speaks — `null` where no schedule is published, rather than a date nobody
promised. An expiry inside ninety days is worth an administrator's attention,
because a provider deprecation is a migration and finding out the week it
happens is finding out too late.

`last_verified: null` means never certified, which is a different state from
certified long ago and needs a different next action.

## Extending, not changing

A new connector implements five things and nothing else:

| Surface | What it is |
|---|---|
| **Connector** | `connect()`, and whatever of `authorize_url` / `discover` / `register_webhook` applies |
| **Manifest** | Everything the console renders itself from |
| **Validation** | `validate()` → structured codes from the closed set |
| **Diagnostics** | `diagnose()` → what only this connector can measure |
| **Repair** | Declared actions, and `repair()` to answer them |

Certification comes free: the scenario list is derived from the manifest, and
`run_scenario()` is optional — a connector that implements none of it scores
`INCONCLUSIVE`, which is the honest answer rather than a failure.

**What would justify unfreezing.** Not a connector needing a new field —
that is what `params`, `diagnostics` and `model_params` are for. The bar is
the one that was met three times before: *several independent connectors
hitting the same wall*, where each has to work around the contract in a way
that is individually reasonable and collectively a bug. One connector wanting
something is a connector; three wanting the same thing is a contract.
