// Reproduces the pre-conversion status badge span from runs_list.html exactly: a
// single span carrying the base badge class plus the status-specific modifier class,
// with the status label as its text.
//
// badgeClass/label are consumed as plain server-computed strings -- the
// status-to-class and status-to-label vocabulary has exactly one owner,
// app/routes/templating.py's badge_class_filter/badge_label_filter, and is never
// re-derived here.
//
// The former `js-status-badge` query-hook class is deliberately NOT reproduced:
// React holds this state and re-renders it directly (plan 22-10's poller re-renders
// via props, not a DOM query), so a script-hook class name here would be dead markup
// the moment it existed.
export function StatusBadge({
  badgeClass,
  label,
}: {
  badgeClass: string;
  label: string;
}) {
  return <span className={`badge badge-${badgeClass}`}>{label}</span>;
}
