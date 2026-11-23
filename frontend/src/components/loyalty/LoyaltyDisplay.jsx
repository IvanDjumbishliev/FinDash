import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { FiX } from "react-icons/fi";
import api from "../../api";
import { receiptApiError } from "../../receiptScanner";

export default function LoyaltyDisplay({ card, onClose, onEdit, onImageChanged }) {
  const dialog = useRef(null);
  const canvas = useRef(null);
  const [codeStatus, setCodeStatus] = useState("loading");
  const [image, setImage] = useState(null);
  const [file, setFile] = useState(null);
  const [loyaltyOnly, setLoyaltyOnly] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const endpoint = `/api/loyalty-cards/${card.id}/image/`;

  useEffect(() => {
    const modal = dialog.current;
    modal.showModal();
    return () => { pending.current?.abort(); modal.close(); };
  }, []);

  useEffect(() => {
    if (card.code_format === "none") return;
    let mounted = true;
    import("../../loyaltyCode").then(({ drawLoyaltyCode }) => {
      if (mounted) setCodeStatus(drawLoyaltyCode(canvas.current, card.code_format, card.identifier) ? "ready" : "unavailable");
    }).catch(() => { if (mounted) setCodeStatus("unavailable"); });
    return () => { mounted = false; };
  }, [card.code_format, card.identifier]);

  useEffect(() => () => { if (image) URL.revokeObjectURL(image); }, [image]);

  async function act(work) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      await work({ signal: controller.signal, timeout: 15000 });
    } catch (failure) {
      if (!controller.signal.aborted) setError(receiptApiError(failure, "Could not manage this image. Try again."));
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function upload(event) {
    event.preventDefault();
    if (!file || !loyaltyOnly) return;
    if (file.size > 8 * 1024 * 1024) {
      setError("Choose an image up to 8 MB.");
      return;
    }
    const data = new FormData();
    data.append("file", file);
    data.append("loyalty_only", "true");
    act(async (options) => {
      await api.post(endpoint, data, options);
      if (options.signal.aborted) return;
      setImage(null);
      setFile(null);
      setLoyaltyOnly(false);
      onImageChanged(true);
    });
  }

  return <dialog className="loyalty-fullscreen" ref={dialog} aria-labelledby="loyalty-display-title" onCancel={(event) => {
    event.preventDefault(); onClose();
  }}>
    <div className="loyalty-display-inner">
      <header><div><h2 id="loyalty-display-title">{card.retailer}</h2>{card.label && <p>{card.label}</p>}</div>
        <button className="dash-button" type="button" autoFocus onClick={onClose}><FiX aria-hidden="true" /> Close</button></header>
      <div className="loyalty-scan-surface">
        {card.code_format !== "none" && <>
          <canvas ref={canvas} role="img" aria-label={card.code_format === "qrcode" ? "Membership QR code" : "Membership barcode"}
            hidden={codeStatus !== "ready"} className={card.code_format === "qrcode" ? "loyalty-qr" : "loyalty-barcode"} />
          {codeStatus === "loading" && <p role="status">Preparing membership code…</p>}
          {codeStatus === "unavailable" && <p role="status">The code couldn’t be rendered. Show the original card at checkout.</p>}
        </>}
        <p className="loyalty-identifier">{card.identifier}</p>
      </div>
      {error && <p role="alert" className="loyalty-note">{error}</p>}
      <div className="dash-actions loyalty-display-actions">
        {card.has_image && <button className="dash-button" type="button" disabled={busy} onClick={() => {
          if (image) { setImage(null); return; }
          act(async (options) => {
            const { data } = await api.get(endpoint, { ...options, responseType: "blob" });
            if (!options.signal.aborted) setImage(URL.createObjectURL(data));
          });
        }}>{image ? "Hide original image" : "Show original image"}</button>}
        <button className="dash-button" type="button" disabled={busy} onClick={onEdit}>Edit card</button>
      </div>
      {image && <img className="loyalty-original" src={image} alt="Uploaded loyalty card" />}
      <details className="loyalty-image-controls">
        <summary>Manage card image</summary>
        <form onSubmit={upload}>
          <label>{card.has_image ? "Replace image" : "Choose an image"}
            <input key={card.has_image ? "attached" : "empty"} type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
              disabled={busy} onChange={(event) => { setFile(event.target.files[0] || null); setError(""); }} />
          </label>
          <label className="loyalty-check"><input type="checkbox" checked={loyaltyOnly} disabled={busy}
            onChange={(event) => setLoyaltyOnly(event.target.checked)} /> This image contains only a loyalty card.</label>
          <div className="dash-actions">
            <button className="dash-button dash-primary" type="submit" disabled={busy || !file || !loyaltyOnly}>Save image</button>
            {card.has_image && <button className="dash-button" type="button" disabled={busy} onClick={() => act(async (options) => {
              await api.delete(endpoint, options);
              if (options.signal.aborted) return;
              setImage(null);
              setFile(null);
              setLoyaltyOnly(false);
              onImageChanged(false);
            })}>Remove image</button>}
          </div>
        </form>
      </details>
    </div>
  </dialog>;
}

LoyaltyDisplay.propTypes = {
  card: PropTypes.shape({
    id: PropTypes.string.isRequired, retailer: PropTypes.string.isRequired, label: PropTypes.string,
    code_format: PropTypes.string.isRequired, identifier: PropTypes.string.isRequired, has_image: PropTypes.bool.isRequired,
  }).isRequired,
  onClose: PropTypes.func.isRequired, onEdit: PropTypes.func.isRequired, onImageChanged: PropTypes.func.isRequired,
};
