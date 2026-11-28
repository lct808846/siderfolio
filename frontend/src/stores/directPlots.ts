import { defineStore } from 'pinia'
import { plottingApi } from '../api/plotting'
import { tablesApi } from '../api/tables'

export interface DirectPlotJob {
  id: string
  conversationId: string
  projectId: string
  datasetId: string
  title: string
  status: 'running' | 'completed' | 'failed'
  runId: string
  files: string[]
  error: string
  createdAt: number
}

export interface DirectPlotEnqueueInput {
  conversationId: string
  projectId: string
  datasetId: string
  title: string
  chart: 'scatter' | 'line' | 'histogram' | 'errorbar'
  columns: string[]
  axes: Record<string, string>
  explanation: string
  warnings: string[]
  script: string
}

interface StoredDirectPlot {
  projectId: string
  runId: string
  title: string
  files: string[]
}

function storageKey(conversationId: string): string {
  return `astroagent.conv_direct_plots.${conversationId || 'draft'}`
}

function readStored(conversationId: string): StoredDirectPlot[] {
  try {
    const raw = sessionStorage.getItem(storageKey(conversationId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persistCompleted(conversationId: string, entry: StoredDirectPlot) {
  try {
    const existing = readStored(conversationId).filter(item => item.runId !== entry.runId)
    existing.unshift(entry)
    sessionStorage.setItem(storageKey(conversationId), JSON.stringify(existing.slice(0, 20)))
  } catch {
    // Ignore storage quota errors.
  }
}

let eventSeq = 0

export const useDirectPlots = defineStore('directPlots', {
  state: () => ({
    jobs: [] as DirectPlotJob[],
    revision: 0,
    lastCompleted: null as { seq: number; job: DirectPlotJob } | null,
    lastError: null as { seq: number; conversationId: string; title: string; message: string } | null,
  }),
  getters: {
    runningFor: state => (conversationId: string) =>
      state.jobs.filter(j => j.conversationId === (conversationId || 'draft') && j.status === 'running'),
    completedFor: state => (conversationId: string): StoredDirectPlot[] => {
      void state.revision
      const cid = conversationId || 'draft'
      const merged: StoredDirectPlot[] = []
      const seen = new Set<string>()
      for (const job of state.jobs) {
        if (job.conversationId === cid && job.status === 'completed' && job.runId && !seen.has(job.runId)) {
          seen.add(job.runId)
          merged.push({
            projectId: job.projectId,
            runId: job.runId,
            title: job.title,
            files: job.files,
          })
        }
      }
      for (const saved of readStored(cid)) {
        if (saved.runId && !seen.has(saved.runId)) {
          seen.add(saved.runId)
          merged.push(saved)
        }
      }
      return merged
    },
  },
  actions: {
    enqueue(input: DirectPlotEnqueueInput): DirectPlotJob {
      const cid = input.conversationId || 'draft'
      const job: DirectPlotJob = {
        id: crypto.randomUUID(),
        conversationId: cid,
        projectId: input.projectId,
        datasetId: input.datasetId,
        title: input.title,
        status: 'running',
        runId: '',
        files: [],
        error: '',
        createdAt: Date.now(),
      }
      this.jobs.unshift(job)
      this.revision++
      void this._execute(job.id, input)
      return job
    },
    async _execute(jobId: string, input: DirectPlotEnqueueInput) {
      const findJob = () => this.jobs.find(j => j.id === jobId)
      try {
        const bridged = await tablesApi.sendToPlot(input.projectId, input.datasetId)
        const planOp = await plottingApi.customPlan(input.projectId, crypto.randomUUID(), {
          dataset_id: bridged.plot_dataset.id,
          model_id: 'direct-table-plot',
          question: input.explanation,
          proposal: {
            engine: 'python',
            chart: input.chart,
            title: input.title,
            columns: input.columns,
            axes: input.axes,
            filters: [],
            explanation: input.explanation,
            warnings: input.warnings,
            script: input.script,
          },
        })
        const runOp = await plottingApi.run(input.projectId, crypto.randomUUID(), {
          plan_id: planOp.id,
          confirm_execute: true,
        })
        const current = findJob()
        if (!current) return
        if (runOp.state === 'completed') {
          current.status = 'completed'
          current.runId = runOp.id
          current.files = [...(runOp.files || [])]
          persistCompleted(current.conversationId, {
            projectId: current.projectId,
            runId: current.runId,
            title: current.title,
            files: current.files,
          })
          this.revision++
          this.lastCompleted = { seq: ++eventSeq, job: { ...current, files: [...current.files] } }
        } else {
          const msg = runOp.error || '隔离容器执行绘图脚本失败。'
          current.status = 'failed'
          current.error = msg
          this.revision++
          this.lastError = {
            seq: ++eventSeq,
            conversationId: current.conversationId,
            title: current.title,
            message: msg,
          }
        }
      } catch (e) {
        const current = findJob()
        const msg = e instanceof Error ? e.message : '后台绘图失败，请核对所选列后重试。'
        if (current) {
          current.status = 'failed'
          current.error = msg
        }
        this.revision++
        this.lastError = {
          seq: ++eventSeq,
          conversationId: input.conversationId || 'draft',
          title: input.title,
          message: msg,
        }
      }
    },
    dismissError() {
      this.lastError = null
    },
  },
})
