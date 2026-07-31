/**
 * What the connector SDK sends, as the console sees it.
 *
 * Every one of these mirrors a backend schema in
 * `api/schemas/channel_connect.py`. Nothing here names a channel: the console
 * renders a step from its `kind` and a connector from its manifest, so adding
 * Slack or RCS changes the backend and nothing in this directory.
 *
 * Everything a customer reads arrives as a **translation key**, never as a
 * sentence. That is why almost every field below is named `*_key` — a server
 * that sent English prose would produce a console that can only ever be
 * English, and this product ships Arabic.
 */

/** How a step is rendered. Six values cover every connector and every one
 * planned; the console switches on this and never on the channel. */
export type StepKind =
  | 'select'
  | 'oauth_redirect'
  | 'form'
  | 'resource_picker'
  | 'checklist'
  | 'summary'

export type StepId = 'select' | 'authenticate' | 'discover' | 'verify' | 'connect'

export type StepState = 'complete' | 'active' | 'pending'

export interface WizardStep {
  id: StepId
  kind: StepKind
  title_key: string
  /** True when the step needs no input — the console shows it and moves on. */
  automatic: boolean
  state: StepState
}

/** One input the console renders without knowing what it means. */
export interface ConnectField {
  name: string
  kind: 'text' | 'secret' | 'number' | 'boolean' | 'select'
  label_key: string
  required: boolean
  help_key: string | null
  placeholder: string | null
  /** `[value, labelKey]` pairs for a select. */
  options: string[][]
  /** Text with a copy button beside it — a command to paste into a provider's
   * bot, a URL for their dashboard. Present exactly when the customer has to
   * do something outside Blink Engage. */
  copyable: string | null
}

export interface DiscoveredResource {
  id: string
  label: string
  group_key: string | null
  detail: Record<string, string>
  /** Set when it cannot be chosen. Shown rather than hidden: a customer who
   * cannot find their page assumes the product is broken. */
  unavailable_reason: string | null
}

/** One finding from the connector's validation. A code from a closed set,
 * never a sentence. */
export interface ConnectCheck {
  code: string
  /** Whether this stops the connection. Decided by the server, centrally, so
   * one channel cannot block on what another waves through. */
  blocks: boolean
  channel_type: string
  params: Record<string, string>
  /** A repair from the manifest that would fix this. */
  repair_action: string | null
  /** Copy for something only the customer can change, in the provider's own
   * app — the honest answer when there is no button. */
  instructions_key: string | null
}

export interface WizardSession {
  session_id: string
  channel_types: string[]
  template_key: string | null
  using_oauth: boolean
  completed: boolean
  steps: WizardStep[]
  current_step: WizardStep
  fields: ConnectField[]
  resources: DiscoveredResource[]
  checks: ConnectCheck[]
  authorize_url: string | null
}

export type Capability =
  | 'oauth'
  | 'auto_discovery'
  | 'webhooks'
  | 'automatic_webhook_registration'
  | 'shared_webhook'
  | 'token_refresh'
  | 'health_checks'
  | 'embedded_signup'
  | 'manual_configuration'

export interface CapabilityState {
  capability: Capability
  available: boolean
  /** A code the console translates — never a sentence. */
  reason: string | null
}

/** The eight states a customer sees, resolved by the server from the
 * connector's declared maturity and this installation's runtime availability.
 * The console badges one value and does not need to know which axis produced
 * it. */
export type LifecycleState =
  | 'available'
  | 'preview'
  | 'beta'
  | 'production'
  | 'deprecated'
  | 'disabled'
  | 'maintenance'
  | 'end_of_life'

export interface ConnectorProfile {
  channel_type: string
  declares: Capability[]
  states: CapabilityState[]
  /** False when there is no way to connect this here — shown greyed with the
   * reason rather than hidden, since a channel that silently vanishes looks
   * like one Blink Engage does not support. */
  connectable: boolean
  lifecycle: LifecycleState
  warns: boolean
  platform_supported: boolean
}

export interface FeatureSupport {
  feature: string
  /** `both` | `inbound` | `outbound`. The field that makes the matrix honest:
   * a channel that receives media and cannot send it says so. */
  direction: 'both' | 'inbound' | 'outbound'
  note_key: string | null
}

export interface VersionInfo {
  connector: string
  /** The **provider's** API version — `v21.0`, `2010-04-01`, or empty. */
  api: string
  minimum_platform: string
}

export interface ResourceSpec {
  key: string
  title_key: string
  /** What the picker says when discovery finds nothing — the difference
   * between a dead end and an explanation. */
  empty_key: string
  multiple: boolean
}

export interface VerificationSpec {
  key: string
  title_key: string
  codes: string[]
}

export interface RepairAction {
  id: string
  title_key: string
  description_key: string
  confirm: boolean
  confirm_key: string | null
  permission: string
  available_during_setup: boolean
}

export interface DocumentationLink {
  key: string
  url: string
}

/** Everything the console needs to render a connector, and nothing else.
 * This is the contract that makes the wizard a renderer. */
export interface ConnectorManifest {
  channel_type: string
  name_key: string
  description_key: string
  category: string
  /** An identifier the console maps to an asset, never a URL. */
  icon: string
  capabilities: Capability[]
  auth_methods: string[]
  required_permissions: string[]
  required_credentials: ConnectField[]
  required_resources: ResourceSpec[]
  verification_steps: VerificationSpec[]
  repair_actions: RepairAction[]
  supported_features: FeatureSupport[]
  documentation: DocumentationLink[]
  maturity: string
  versions: VersionInfo
}

export interface ConnectionTemplate {
  key: string
  channel_types: string[]
  title_key: string
  description_key: string
  recommended: boolean
}

export interface ConnectCatalog {
  connectors: ConnectorProfile[]
  templates: ConnectionTemplate[]
  manifests: ConnectorManifest[]
}

export interface ConnectedChannel {
  id: string
  channel_type: string
  display_name: string
}

export interface ConnectResult {
  channels: ConnectedChannel[]
}
