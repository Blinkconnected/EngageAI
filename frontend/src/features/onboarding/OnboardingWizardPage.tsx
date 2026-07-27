import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Paper, Stack, Step, StepLabel, Stepper, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useCompanyQuery, useUpdateCompanyMutation } from '../company/api'
import { ChannelsStep } from './steps/ChannelsStep'
import { CompanyInfoStep } from './steps/CompanyInfoStep'
import { ErpIntegrationStep } from './steps/ErpIntegrationStep'
import { TeamSetupStep } from './steps/TeamSetupStep'
import type { Company } from '../company/types'

const STEPS = ['Company Information', 'Team Setup', 'Channels', 'ERP Integration'] as const

export function OnboardingWizardPage() {
  const companyQuery = useCompanyQuery()

  return (
    <Box sx={{ maxWidth: 760, mx: 'auto' }}>
      {companyQuery.isPending && <LoadingState label="Loading…" />}
      {companyQuery.isError && (
        <ErrorState error={companyQuery.error} onRetry={() => companyQuery.refetch()} />
      )}
      {companyQuery.data && <OnboardingWizard company={companyQuery.data} />}
    </Box>
  )
}

function OnboardingWizard({ company }: { company: Company }) {
  const [activeStep, setActiveStep] = useState(0)
  const navigate = useNavigate()
  const finishMutation = useUpdateCompanyMutation()

  function finish() {
    finishMutation.mutate(
      { settings: { onboarding: { completed: true } } },
      { onSuccess: () => navigate('/', { replace: true }) },
    )
  }

  return (
    <Paper variant="outlined" sx={{ p: 4 }}>
      <Stack spacing={1} sx={{ mb: 3 }}>
        <Typography variant="h5" component="h1" sx={{ fontWeight: 600 }}>
          Set up {company.name}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          A few quick steps to get your workspace ready. You can change any of this later in
          Settings.
        </Typography>
      </Stack>

      <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
        {STEPS.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <Box sx={{ mb: 4 }}>
        {activeStep === 0 && <CompanyInfoStep company={company} />}
        {activeStep === 1 && <TeamSetupStep />}
        {activeStep === 2 && <ChannelsStep />}
        {activeStep === 3 && <ErpIntegrationStep company={company} />}
      </Box>

      <Stack direction="row" spacing={2} sx={{ justifyContent: 'space-between' }}>
        <Button onClick={finish} disabled={finishMutation.isPending}>
          Skip setup
        </Button>
        <Stack direction="row" spacing={2}>
          {activeStep > 0 && (
            <Button onClick={() => setActiveStep((step) => step - 1)}>Back</Button>
          )}
          {activeStep < STEPS.length - 1 ? (
            <Button variant="contained" onClick={() => setActiveStep((step) => step + 1)}>
              Next
            </Button>
          ) : (
            <Button variant="contained" onClick={finish} disabled={finishMutation.isPending}>
              {finishMutation.isPending ? 'Finishing…' : 'Finish'}
            </Button>
          )}
        </Stack>
      </Stack>
    </Paper>
  )
}
