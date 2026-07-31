# The connector framework

Blink Engage is a messaging platform. A channel is a transport adapter.

That is a product principle, and this is where it stops being a slogan: a
**capability contract** every connector answers, and a connection flow
*derived* from the answers. The wizard that connects WhatsApp is the same
wizard, running the same code, that connects Telegram — and that will connect
Slack, Teams, RCS, LINE or WeChat.

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

Three members is the bar: `channel_type`, `declares`, `connect`.

```python
@ConnectorRegistry.register("slack")
class SlackConnector(Connector):
    app_key = "slack"
    declares = frozenset({Capability.OAUTH, Capability.AUTO_DISCOVERY, ...})

    async def connect(self, *, company_id, attempt): ...
```

Everything else — `credential_fields`, `authorize_url`, `discover`, `check`,
`register_webhook`, `repair` — is optional and defaults to the honest answer.

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
