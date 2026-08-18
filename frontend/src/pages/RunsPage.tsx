// Reproduces app/templates/runs_list.html's former React-mount region (the
// .table-scroll table + the empty state) exactly -- same class names from
// app/static/style.css, same column order, same per-row data attributes. No new
// class name, no stylesheet: the component library already exists.
//
// Field names below are snake_case to match the Pydantic DTO's JSON output
// verbatim (app/schemas/runs_list.py) -- no casing translation layer.
//
// The three `js-` poller hook classes the old vanilla-JS poller looked up
// (`js-status-badge`, `js-failure-secondary`, `js-failure-summary`) are deliberately
// NOT reproduced here: React holds this state and re-renders it directly, so a DOM
// query-selector hook would be dead markup the moment it existed. Live polling is
// wired via usePoller below, one instance per in-flight row, replacing the deleted
// test_script_hook_classes_carry_js_prefix_and_stay_out_of_css guard with a
// component test asserting the badge updates in place.
//
// The status cluster, queue badge and failure presentation are lifted into three
// focused components (StatusBadge/QueueBadge/FailureSummary) so each is independently
// testable and each owns exactly one piece of the pre-conversion markup.

import { useState } from "react";

import { FailureSummary, type FailureInfo } from "../components/FailureSummary";
import { QueueBadge } from "../components/QueueBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePoller } from "../hooks/usePoller";

export type { FailureInfo };

export interface RunListRow {
  id: string;
  created_at: string | null;
  created_at_display: string;
  business_name: string;
  status: string;
  badge_class: string;
  badge_label: string;
  queue_label: string | null;
  queue_badge_class: string;
  has_open_job: boolean;
  failure: FailureInfo;
  summary_gate_reason: string | null;
  employee_count: number;
}

export interface RunsListPage {
  runs: RunListRow[];
  in_flight_statuses: string[];
}

// The seven fields a status poll tick replaces wholesale, mirroring the Pydantic
// RunStatusPoll shape (app/schemas/run_status.py) field-for-field. RunListRow already
// declares all seven; this Pick avoids restating them.
type PollUpdate = Pick<
  RunListRow,
  | "status"
  | "badge_class"
  | "badge_label"
  | "queue_label"
  | "queue_badge_class"
  | "has_open_job"
  | "failure"
>;

function pickVolatile(run: RunListRow): PollUpdate {
  return {
    status: run.status,
    badge_class: run.badge_class,
    badge_label: run.badge_label,
    queue_label: run.queue_label,
    queue_badge_class: run.queue_badge_class,
    has_open_job: run.has_open_job,
    failure: run.failure,
  };
}

export function RunsPage({ data }: { data: RunsListPage }) {
  const { runs, in_flight_statuses: inFlightStatuses } = data;

  if (runs.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-state__title">No payroll runs yet</p>
        <p className="text-muted">
          Use the Send Test Email button below to fire a demo fixture through the
          pipeline.
        </p>
      </div>
    );
  }

  return (
    <div className="table-scroll" role="region" tabIndex={0} aria-label="Payroll runs">
      <table>
        <thead>
          <tr>
            <th>Created</th>
            <th>Business</th>
            <th>Status</th>
            <th>Summary</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <RunRow key={run.id} run={run} inFlightStatuses={inFlightStatuses} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunRow({
  run,
  inFlightStatuses,
}: {
  run: RunListRow;
  inFlightStatuses: string[];
}) {
  // Holds only the seven volatile fields; the static fields (id, created_at,
  // business_name, summary_gate_reason, employee_count) never change after the
  // initial server render, so they stay read straight off `run` below rather than
  // being duplicated into state.
  const [volatile, setVolatile] = useState<PollUpdate>(() => pickVolatile(run));
  const merged: RunListRow = { ...run, ...volatile };

  const inFlight = inFlightStatuses.includes(merged.status);
  const shouldPoll = inFlight || merged.has_open_job;

  const { stage, reason, attempts } = merged.failure;
  const hasFailureSummary = Boolean(stage || reason || attempts);

  return (
    <tr
      data-run-id={merged.id}
      data-in-flight={inFlight ? "true" : "false"}
      data-has-open-job={merged.has_open_job ? "true" : "false"}
    >
      <td className="cell-time">{merged.created_at_display}</td>
      <td>{merged.business_name}</td>
      <td>
        <span className="status-cluster">
          <StatusBadge badgeClass={merged.badge_class} label={merged.badge_label} />
          <QueueBadge
            label={merged.queue_label}
            badgeClass={merged.queue_badge_class}
            hasOpenJob={merged.has_open_job}
          />
        </span>
      </td>
      <td className="text-muted">
        {hasFailureSummary ? (
          <FailureSummary failure={merged.failure} />
        ) : merged.summary_gate_reason ? (
          merged.summary_gate_reason
        ) : merged.employee_count ? (
          `${merged.employee_count} employee${merged.employee_count !== 1 ? "s" : ""}`
        ) : (
          "—"
        )}
      </td>
      <td>
        <a href={`/runs/${merged.id}`}>View</a>
      </td>
      {shouldPoll ? (
        <RowPoller
          runId={merged.id}
          inFlightStatuses={inFlightStatuses}
          onUpdate={setVolatile}
        />
      ) : null}
    </tr>
  );
}

// Mounted only for rows that are in-flight or carry an open job -- a settled row with
// no open job renders no RowPoller at all, so it issues zero requests. This is a
// conditionally RENDERED component, not a conditionally CALLED hook: usePoller is
// still called unconditionally from RowPoller's own top level, so the Rules of Hooks
// hold. When a tick settles the row, the next render's shouldPoll becomes false,
// RowPoller unmounts, and usePoller's own cleanup clears the interval -- the row stops
// polling without any extra bookkeeping here.
function RowPoller({
  runId,
  inFlightStatuses,
  onUpdate,
}: {
  runId: string;
  inFlightStatuses: string[];
  onUpdate: (data: PollUpdate) => void;
}) {
  usePoller<PollUpdate>(
    `/runs/${runId}/status`,
    {
      intervalMs: 2000,
      maxAttempts: 60,
      stopWhen: (data) => !inFlightStatuses.includes(data.status) && !data.has_open_job,
    },
    onUpdate,
  );
  return null;
}
