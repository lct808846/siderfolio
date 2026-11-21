-- V1.7 additive schema. Apply explicitly with the existing application database role.
BEGIN;
CREATE TABLE IF NOT EXISTS public.compute_tasks (
    id uuid PRIMARY KEY,
    account_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
    project_id uuid NOT NULL,
    namespace text NOT NULL CHECK (namespace ~ '^aa_[0-9a-f]{32}$'),
    name text NOT NULL,
    source text NOT NULL,
    origin_id uuid,
    parameters jsonb NOT NULL,
    parameter_sha256 text NOT NULL,
    revision integer NOT NULL DEFAULT 0,
    state text NOT NULL CHECK (state IN (
        'draft', 'queued', 'running', 'cancelling', 'succeeded', 'failed',
        'cancelled', 'interrupted'
    )),
    events jsonb NOT NULL DEFAULT '[]',
    request_id uuid,
    confirmed_revision integer,
    queued_at timestamptz,
    attempt_id uuid,
    lease_until timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    sample_count integer NOT NULL,
    samples_completed integer NOT NULL DEFAULT 0,
    error text,
    result jsonb,
    UNIQUE (account_id, project_id, request_id)
);
CREATE INDEX IF NOT EXISTS compute_tasks_owner ON public.compute_tasks(account_id, project_id, created_at);
CREATE INDEX IF NOT EXISTS compute_tasks_queue ON public.compute_tasks(queued_at) WHERE state = 'queued';
CREATE UNIQUE INDEX IF NOT EXISTS compute_tasks_execution_slot ON public.compute_tasks ((1))
    WHERE state IN ('running', 'cancelling');
REVOKE ALL ON public.compute_tasks FROM PUBLIC;
COMMIT;
