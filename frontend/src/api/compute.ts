import { apiUrl, download, request } from './index'
import type { components, paths } from '../types/generated'

export type ComputeTask = components['schemas']['ComputeTask']
export type ComputeList = components['schemas']['ComputeList']
export type ComputeStatus = components['schemas']['ComputeStatus']
export type ComputeDraft = components['schemas']['ComputeDraft']
export type ComputeConfirm = components['schemas']['ComputeConfirm']
export type ComputeResult =
  paths['/api/v1/projects/{project_id}/compute-tasks/{task_id}/result']['get']['responses'][200]['content']['application/json']
export type ComputeParameters = components['schemas']['SimulationParameters']
export type ComputeProposal = components['schemas']['ComputeProposal']
export type PlotKind = 'snapshot' | 'trajectory' | 'energy'

let handoff: { project: string; description: string; model?: string } | undefined
export function setComputeHandoff(project: string, description: string, model?: string) {
  handoff = { project, description: description.slice(0, 6000), model }
}
export function takeComputeHandoff(project: string) {
  if (handoff?.project !== project) return
  const value = handoff
  handoff = undefined
  return value
}

const base = (project: string) => `/api/v1/projects/${encodeURIComponent(project)}/compute-tasks`
const path = (project: string, id: string) => `${base(project)}/${encodeURIComponent(id)}`

export const computeApi = {
  status: () => request<ComputeStatus>('/api/v1/compute/status'),
  list: (project: string) => request<ComputeList>(base(project)),
  template: (project: string) => request<ComputeParameters>(`${base(project)}/templates/binary`),
  describe: (project: string, description: string, modelId?: string) =>
    request<ComputeProposal>(`${base(project)}/describe`, 'POST', { description, model_id: modelId }),
  create: (project: string, draft: ComputeDraft) => request<ComputeTask>(base(project), 'POST', draft),
  detail: (project: string, id: string) => request<ComputeTask>(path(project, id)),
  update: (project: string, id: string, revision: number, draft: ComputeDraft) =>
    request<ComputeTask>(path(project, id), 'PATCH', { ...draft, expected_revision: revision }),
  confirm: (project: string, id: string, confirmation: ComputeConfirm) =>
    request<ComputeTask>(`${path(project, id)}/confirm`, 'POST', confirmation),
  cancel: (project: string, id: string) => request<ComputeTask>(`${path(project, id)}/cancel`, 'POST'),
  copy: (project: string, id: string) => request<ComputeTask>(`${path(project, id)}/copy`, 'POST'),
  remove: (project: string, id: string) => request<void>(path(project, id), 'DELETE'),
  result: (project: string, id: string) => request<ComputeResult>(`${path(project, id)}/result`),
  plot: (project: string, id: string, kind: PlotKind, sample?: number) =>
    apiUrl(`${path(project, id)}/plots/${kind}${sample === undefined ? '' : `?sample=${sample}`}`),
  snapshots: (project: string, id: string) =>
    download(`${path(project, id)}/snapshots`, `astroagent-snapshots-${id}.csv`, 'text/csv'),
  download(project: string, id: string, plots: PlotKind[], snapshotIndex: number) {
    const query = new URLSearchParams()
    plots.forEach(plot => query.append('plots', plot))
    if (plots.includes('snapshot')) query.set('sample', String(snapshotIndex))
    return download(`${path(project, id)}/archive?${query}`, `astroagent-experiment-${id}.zip`)
  },
}
