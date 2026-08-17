// Reproduces the pre-conversion queue badge span from runs_list.html exactly: a badge
// span carrying the queue-specific modifier class plus the queue-badge class, an
// aria-live="polite" attribute, hidden whenever there is no open job, showing the
// queue label text otherwise.
//
// Kept hidden (not unmounted) when there is no open job, and its text is always
// forced to the empty string rather than the literal "null" -- a screen reader must
// hear a queue transition announced via the same live-region element every time, not
// a fresh element appearing and disappearing.
export function QueueBadge({
  label,
  badgeClass,
  hasOpenJob,
}: {
  label: string | null;
  badgeClass: string;
  hasOpenJob: boolean;
}) {
  return (
    <span
      className={`badge badge-${badgeClass} queue-badge`}
      aria-live="polite"
      hidden={!hasOpenJob}
    >
      {label ?? ""}
    </span>
  );
}
