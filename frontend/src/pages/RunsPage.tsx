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
// query-selector hook would be dead markup the moment it existed. Live polling
// (usePoller) is a later plan's job -- this page renders the initial snapshot only.
//
// The status cluster, queue badge and failure presentation are lifted into three
// focused components (StatusBadge/QueueBadge/FailureSummary) so each is independently
// testable and each owns exactly one piece of the pre-conversion markup.

import { FailureSummary, type FailureInfo } from "../components/FailureSummary";
import { QueueBadge } from "../components/QueueBadge";
import { StatusBadge } from "../components/StatusBadge";

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
            <RunRow
              key={run.id}
              run={run}
              inFlight={inFlightStatuses.includes(run.status)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunRow({ run, inFlight }: { run: RunListRow; inFlight: boolean }) {
  const { stage, reason, attempts } = run.failure;
  const hasFailureSummary = Boolean(stage || reason || attempts);

  return (
    <tr
      data-run-id={run.id}
      data-in-flight={inFlight ? "true" : "false"}
      data-has-open-job={run.has_open_job ? "true" : "false"}
    >
      <td className="cell-time">{run.created_at_display}</td>
      <td>{run.business_name}</td>
      <td>
        <span className="status-cluster">
          <StatusBadge badgeClass={run.badge_class} label={run.badge_label} />
          <QueueBadge
            label={run.queue_label}
            badgeClass={run.queue_badge_class}
            hasOpenJob={run.has_open_job}
          />
        </span>
      </td>
      <td className="text-muted">
        {hasFailureSummary ? (
          <FailureSummary failure={run.failure} />
        ) : run.summary_gate_reason ? (
          run.summary_gate_reason
        ) : run.employee_count ? (
          `${run.employee_count} employee${run.employee_count !== 1 ? "s" : ""}`
        ) : (
          "—"
        )}
      </td>
      <td>
        <a href={`/runs/${run.id}`}>View</a>
      </td>
    </tr>
  );
}
