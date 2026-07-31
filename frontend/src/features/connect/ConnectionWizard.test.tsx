import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { queryClient } from '../../app/queryClient'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { ConnectionWizard } from './ConnectionWizard'
import { ChannelPicker } from './ChannelPicker'
import type { ConnectorManifest, WizardSession } from './types'

/**
 * The wizard renders whatever the server describes.
 *
 * Every test here uses a **fictional** channel. If one ever needs to know
 * what WhatsApp is, the thing this milestone was built for has stopped
 * working — the console would then need changing for every channel added
 * after it, which is precisely the cost the connector SDK exists to avoid.
 */

const MANIFEST: ConnectorManifest = {
  channel_type: 'fictional',
  name_key: 'connect.fictional.name',
  description_key: 'connect.fictional.description',
  category: 'messaging',
  icon: 'fictional',
  capabilities: ['manual_configuration', 'health_checks'],
  auth_methods: ['credentials'],
  required_permissions: [],
  required_credentials: [],
  required_resources: [],
  verification_steps: [],
  repair_actions: [],
  supported_features: [],
  documentation: [],
  maturity: 'production',
  versions: { connector: '1.0.0', api: '', minimum_platform: '1.0.0' },
}

function session(overrides: Partial<WizardSession> = {}): WizardSession {
  const steps: WizardSession['steps'] = [
    { id: 'select', kind: 'select', title_key: 'connect.step.select', automatic: false, state: 'complete' },
    { id: 'authenticate', kind: 'form', title_key: 'connect.step.credentials', automatic: false, state: 'active' },
    { id: 'connect', kind: 'summary', title_key: 'connect.step.connect', automatic: false, state: 'pending' },
  ]
  return {
    session_id: 's-1',
    channel_types: ['fictional'],
    template_key: null,
    using_oauth: false,
    completed: false,
    steps,
    current_step: steps[1],
    fields: [],
    resources: [],
    checks: [],
    authorize_url: null,
    ...overrides,
  }
}

function mockWizard({
  start = session(),
  advanced,
  onAdvance = () => {},
  onConnect = () => {},
}: {
  start?: WizardSession
  advanced?: WizardSession
  onAdvance?: (body: Record<string, unknown>) => void
  onConnect?: () => void
} = {}) {
  server.use(
    http.post(`${API_BASE_URL}/channel-connect/sessions`, () => HttpResponse.json(start, { status: 201 })),
    http.post(`${API_BASE_URL}/channel-connect/sessions/:id/advance`, async ({ request }) => {
      onAdvance((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(advanced ?? start)
    }),
    http.post(`${API_BASE_URL}/channel-connect/sessions/:id/connect`, () => {
      onConnect()
      return HttpResponse.json({
        channels: [{ id: 'c-1', channel_type: 'fictional', display_name: 'Support' }],
      })
    }),
  )
}

describe('ConnectionWizard', () => {
  beforeEach(() => queryClient.clear())

  it('shows the steps the server derived, not a fixed list', async () => {
    // A connector with four steps must show four and one with three, three.
    // A hardcoded stepper would show the same count for both.
    mockWizard()
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    await waitFor(() => expect(screen.getAllByRole('button')).not.toHaveLength(0))
    // Three steps described, three rendered.
    expect(await screen.findByText(/choose a channel/i)).toBeVisible()
    expect(screen.getByText(/enter details/i)).toBeVisible()
    expect(screen.getByText(/review and connect/i)).toBeVisible()
    expect(screen.queryByText(/run checks/i)).not.toBeInTheDocument()
  })

  it('renders a form field it has never heard of', async () => {
    // The whole claim: the console is given a field description and draws it
    // without knowing what the value means.
    mockWizard({
      start: session({
        fields: [
          {
            name: 'invented_credential',
            kind: 'secret',
            label_key: 'connect.fictional.inventedLabel',
            required: true,
            help_key: 'connect.fictional.inventedHelp',
            placeholder: 'abc-123',
            options: [],
            copyable: '/summon',
          },
        ],
      }),
    })
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    // No copy exists for these keys, so the readable fallback runs — which is
    // the behaviour a connector shipped ahead of its translations gets.
    expect(await screen.findByLabelText(/invented label/i)).toBeVisible()
    expect(screen.getByText('/summon')).toBeVisible()
  })

  it('will not continue while a required field is empty', async () => {
    mockWizard({
      start: session({
        fields: [
          {
            name: 'token',
            kind: 'secret',
            label_key: 'connect.fictional.token',
            required: true,
            help_key: null,
            placeholder: null,
            options: [],
            copyable: null,
          },
        ],
      }),
    })
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    const submit = await screen.findByRole('button', { name: /continue/i })
    expect(submit).toBeDisabled()

    await userEvent.setup().type(await screen.findByLabelText(/token/i), 'secret')
    await waitFor(() => expect(submit).toBeEnabled())
  })

  it('sends what the customer typed back under the field names the server gave', async () => {
    const sent: Record<string, unknown>[] = []
    mockWizard({
      start: session({
        fields: [
          {
            name: 'odd_name',
            kind: 'text',
            label_key: 'connect.fictional.odd',
            required: false,
            help_key: null,
            placeholder: null,
            options: [],
            copyable: null,
          },
        ],
      }),
      onAdvance: (body) => sent.push(body),
    })
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    const user = userEvent.setup()
    await user.type(await screen.findByLabelText(/odd/i), 'value')
    await user.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => expect(sent).toHaveLength(1))
    expect((sent[0] as { payload: Record<string, string> }).payload.odd_name).toBe('value')
  })

  it('shows a failing check and refuses to connect through it', async () => {
    // The console mirrors a decision the server already made. It is a
    // courtesy — the server refuses too — but a customer should not be able
    // to press a button that cannot work.
    const summary: WizardSession['steps'][number] = {
      id: 'connect',
      kind: 'summary',
      title_key: 'connect.step.connect',
      automatic: false,
      state: 'active',
    }
    let connected = false
    mockWizard({
      start: session({
        current_step: summary,
        checks: [
          {
            code: 'invalid_token',
            blocks: true,
            channel_type: 'fictional',
            params: {},
            repair_action: null,
            instructions_key: null,
          },
        ],
      }),
      onConnect: () => {
        connected = true
      },
    })
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    const button = await screen.findByRole('button', { name: /^connect$/i })
    expect(button).toBeDisabled()
    expect(connected).toBe(false)
  })

  it('translates a check code rather than showing it', async () => {
    // A raw dotted string in front of a customer is the failure this whole
    // bundle exists to prevent.
    const checklist: WizardSession['steps'][number] = {
      id: 'verify',
      kind: 'checklist',
      title_key: 'connect.step.verify',
      automatic: true,
      state: 'active',
    }
    mockWizard({
      start: session({
        current_step: checklist,
        checks: [
          {
            code: 'missing_permission',
            blocks: true,
            channel_type: 'fictional',
            params: { scopes: 'read_messages' },
            repair_action: null,
            instructions_key: null,
          },
        ],
      }),
    })
    renderAuthenticated(
      <ConnectionWizard manifest={MANIFEST} onClose={() => {}} onConnected={() => {}} />,
    )

    const finding = await screen.findByText(/a permission is missing/i)
    expect(finding).toBeVisible()
    // The parameter was interpolated, not left as braces.
    expect(finding).toHaveTextContent('read_messages')
    expect(document.body.textContent).not.toMatch(/check\.missing_permission/)
  })

  it('connects and reports how many channels were made', async () => {
    let made = 0
    mockWizard({
      start: session({
        current_step: {
          id: 'connect',
          kind: 'summary',
          title_key: 'connect.step.connect',
          automatic: false,
          state: 'active',
        },
      }),
    })
    renderAuthenticated(
      <ConnectionWizard
        manifest={MANIFEST}
        onClose={() => {}}
        onConnected={(count) => {
          made = count
        }}
      />,
    )

    await userEvent.setup().click(await screen.findByRole('button', { name: /^connect$/i }))

    await waitFor(() => expect(made).toBe(1))
  })
})

describe('ChannelPicker', () => {
  beforeEach(() => queryClient.clear())

  function mockCatalog(connectors: Record<string, unknown>[], templates: unknown[] = []) {
    server.use(
      http.get(`${API_BASE_URL}/channel-connect/catalog`, () =>
        HttpResponse.json({
          connectors,
          templates,
          manifests: connectors.map((c) => ({
            ...MANIFEST,
            channel_type: c.channel_type,
            name_key: `connect.${c.channel_type}.name`,
            description_key: `connect.${c.channel_type}.description`,
          })),
        }),
      ),
    )
  }

  const base = {
    channel_type: 'fictional',
    declares: ['manual_configuration'],
    states: [],
    connectable: true,
    lifecycle: 'production',
    warns: false,
    platform_supported: true,
  }

  it('lists whatever the server ships, with no channel list of its own', async () => {
    // Two channels that do not exist. They render because the server said
    // they do — nothing in the picker knows any channel's name.
    mockCatalog([
      { ...base, channel_type: 'invented_channel' },
      { ...base, channel_type: 'another_one' },
    ])
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    // No copy exists for these, so the readable fallback runs — which is what
    // a connector shipped ahead of its translations would show.
    expect(await screen.findByText(/invented channel/i)).toBeVisible()
    expect(screen.getByText(/another one/i)).toBeVisible()
  })

  it('badges a connector that is not production yet', async () => {
    mockCatalog([{ ...base, lifecycle: 'preview', warns: true }])
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    expect(await screen.findByText('Preview')).toBeVisible()
    expect(screen.getByText(/still under active development/i)).toBeVisible()
  })

  it('badges nothing for a production connector', async () => {
    // A chip on every card is a chip nobody reads.
    mockCatalog([{ ...base, lifecycle: 'production', warns: false }])
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    await screen.findByText(/^Fictional$/)
    expect(screen.queryByText('Preview')).not.toBeInTheDocument()
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
  })

  it('shows an unconnectable channel greyed with the reason, rather than hiding it', async () => {
    // A channel that silently vanishes looks like one Blink Engage does not
    // support.
    mockCatalog([{ ...base, connectable: false, platform_supported: false }])
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    expect(await screen.findByText(/needs a newer version/i)).toBeVisible()
  })

  it('says which of disabled and maintenance it is', async () => {
    // Different sentences because they need different actions from the
    // customer: one is permanent until somebody changes it, the other is
    // "try again later".
    mockCatalog([{ ...base, connectable: false, lifecycle: 'maintenance' }])
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    expect(await screen.findByText(/temporarily unavailable/i)).toBeVisible()
  })

  it('offers templates above single channels', async () => {
    mockCatalog(
      [base],
      [
        {
          key: 'bundle',
          channel_types: ['fictional'],
          title_key: 'connect.template.whatsappOnly.title',
          description_key: 'connect.template.whatsappOnly.description',
          recommended: true,
        },
      ],
    )
    renderAuthenticated(<ChannelPicker open onClose={() => {}} onPick={() => {}} />)

    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText(/connect several at once/i)).toBeVisible()
    expect(dialog.getByText(/recommended/i)).toBeVisible()
  })

  it('reports the template key when a bundle is chosen', async () => {
    const picked: unknown[] = []
    mockCatalog(
      [base],
      [
        {
          key: 'bundle',
          channel_types: ['fictional'],
          title_key: 'connect.template.whatsappOnly.title',
          description_key: 'connect.template.whatsappOnly.description',
          recommended: false,
        },
      ],
    )
    renderAuthenticated(
      <ChannelPicker open onClose={() => {}} onPick={(choice) => picked.push(choice)} />,
    )

    await userEvent
      .setup()
      .click(await screen.findByText(/connect one whatsapp business number/i))

    expect(picked).toEqual([{ templateKey: 'bundle' }])
  })
})
