import { useI18n } from "../i18n";

export interface AboutModalProps {
  onClose: () => void;
}

// Permanent "Om prognosen" entry (item 4 of the public-launch UX pass) --
// a lightweight modal reusing the same .modal-backdrop/.modal pattern as
// ReportForm, rather than a separate heavy page. Content mirrors README.md
// (data sources, update cadence) and reuses the existing model disclaimer
// string verbatim rather than inventing a second, possibly-inconsistent
// version of it.
export function AboutModal({ onClose }: AboutModalProps) {
  const { t } = useI18n();

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="about-title">
        {/* A visible x in the corner (in addition to the Stäng button
            further down) means closing never requires scrolling to the
            bottom first -- both call the same onClose. */}
        <div className="modal-header">
          <h2 id="about-title">{t("about.title")}</h2>
          <button type="button" className="icon-button modal-close" onClick={onClose} aria-label={t("about.close")}>
            ✕
          </button>
        </div>

        <div className="field-group">
          <div className="section-title">{t("about.howTitle")}</div>
          <p style={{ margin: 0, fontSize: "0.9rem" }}>{t("about.howBody")}</p>
        </div>

        <div className="field-group">
          <div className="section-title">{t("about.sourcesTitle")}</div>
          <p style={{ margin: 0, fontSize: "0.9rem" }}>{t("about.sourcesBody")}</p>
        </div>

        <div className="field-group">
          <div className="section-title">{t("about.updateTitle")}</div>
          <p style={{ margin: 0, fontSize: "0.9rem" }}>{t("about.updateBody")}</p>
        </div>

        <div className="field-group">
          <div className="section-title">{t("about.limitationsTitle")}</div>
          <p className="model-disclaimer" style={{ fontSize: "0.85rem" }}>
            {t("about.limitationsBody")}
          </p>
        </div>

        <div className="button-row">
          <button type="button" className="button primary" onClick={onClose}>
            {t("about.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
