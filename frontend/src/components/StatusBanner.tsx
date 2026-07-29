export function StatusBanner({
  message,
  tone = "info",
  onRetry,
}: {
  message: string;
  tone?: "info" | "error";
  onRetry?: () => void;
}) {
  return (
    <div className={`status-banner ${tone === "error" ? "error" : ""}`} role="status" aria-live="polite">
      {message}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          style={{ marginLeft: "0.6rem", border: "1px solid currentColor", background: "none", color: "inherit", borderRadius: 6, padding: "0.1rem 0.5rem" }}
        >
          Retry
        </button>
      )}
    </div>
  );
}
