export interface WorkflowHandoffPayload {
  templateId: 'gaia_field' | 'ads_evidence'
  name?: string
  objectName?: string
  ra?: string
  dec?: string
  radius?: string
  limit?: string
  ruwe?: string
  snr?: string
  query?: string
}

let workbenchDraft = ''
let workflowHandoff: WorkflowHandoffPayload | null = null

export function setWorkbenchDraft(text: string) {
  workbenchDraft = text.slice(0, 4000)
}

export function takeWorkbenchDraft(): string {
  const value = workbenchDraft
  workbenchDraft = ''
  return value
}

export function setWorkflowHandoff(payload: WorkflowHandoffPayload) {
  workflowHandoff = { ...payload }
}

export function takeWorkflowHandoff(): WorkflowHandoffPayload | null {
  const value = workflowHandoff
  workflowHandoff = null
  return value
}
