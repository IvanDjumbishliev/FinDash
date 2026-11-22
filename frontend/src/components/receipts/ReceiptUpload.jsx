import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { FiCamera, FiImage, FiRotateCw, FiUploadCloud, FiX } from "react-icons/fi";
import { ACCEPTED_RECEIPT_IMAGES, MAX_RECEIPT_IMAGES } from "../../receiptScanner";

const pageType = PropTypes.shape({
  id: PropTypes.number.isRequired,
  file: PropTypes.instanceOf(File).isRequired,
  turns: PropTypes.number.isRequired,
});

export function ReceiptPhoto({ page, index, onRotate, onRemove }) {
  const image = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const url = URL.createObjectURL(page.file);
    image.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [page.file]);

  return <li className="receipt-photo">
    <div className="receipt-photo-frame">
      <img ref={image} alt={`Receipt photo ${index + 1}`} hidden={failed}
        onError={() => setFailed(true)}
        style={{ transform: `rotate(${page.turns * 90}deg) scale(${page.turns % 2 ? 0.76 : 1})` }} />
      {failed && <p>Preview unavailable. You can still scan this image.</p>}
    </div>
    <span className="receipt-filename">{page.file.name}</span>
    {onRotate && onRemove && <div className="receipt-actions">
      <button className="dash-button" type="button" disabled={failed} onClick={() => onRotate(page.id)}
        aria-label={`Rotate photo ${index + 1} clockwise`}><FiRotateCw aria-hidden="true" /> Rotate</button>
      <button className="dash-button" type="button" onClick={() => onRemove(page.id)}
        aria-label={`Remove photo ${index + 1}`}><FiX aria-hidden="true" /> Remove</button>
    </div>}
  </li>;
}

ReceiptPhoto.propTypes = { page: pageType.isRequired, index: PropTypes.number.isRequired,
  onRotate: PropTypes.func, onRemove: PropTypes.func };

export default function ReceiptUpload({ pages, onFiles, onRotate, onRemove, onScan }) {
  const camera = useRef(null);
  const gallery = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [allowAi, setAllowAi] = useState(false);
  const [dateOrder, setDateOrder] = useState("DMY");

  function select(event, source, replace = false) {
    const files = Array.from(event.target.files);
    if (files.length) onFiles(files, source, replace);
    event.target.value = "";
  }

  return <form onSubmit={(event) => {
    event.preventDefault();
    if (pages.length) onScan({ allowAi, dateOrder });
  }}>
    <div className="receipt-upload-panel">
      <div className="receipt-drop" data-dragging={dragging}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (event.dataTransfer.files.length) onFiles(Array.from(event.dataTransfer.files), "upload");
        }}>
        <FiUploadCloud className="receipt-upload-icon" aria-hidden="true" />
        <p><strong>Drop receipt photos here</strong></p>
        <p>JPEG, PNG, WebP, or HEIC/HEIF. Up to three photos and 8 MB total.</p>
        <div className="receipt-actions">
          <button className="dash-button" type="button" onClick={() => { camera.current.dataset.retake = "false"; camera.current.click(); }} disabled={pages.length >= MAX_RECEIPT_IMAGES}>
            <FiCamera aria-hidden="true" /> Take photo
          </button>
          <button className="dash-button" type="button" onClick={() => gallery.current.click()} disabled={pages.length >= MAX_RECEIPT_IMAGES}>
            <FiImage aria-hidden="true" /> Choose from gallery
          </button>
          {pages.length > 0 && <button className="dash-button" type="button" onClick={() => { camera.current.dataset.retake = "true"; camera.current.click(); }}>
            Retake receipt
          </button>}
        </div>
        <input id="receipt-camera" aria-label="Receipt camera" hidden type="file" ref={camera}
          accept="image/*" capture="environment"
          onChange={(event) => select(event, "camera", event.target.dataset.retake === "true")} />
        <input id="receipt-gallery" aria-label="Receipt gallery" hidden type="file" ref={gallery}
          accept={ACCEPTED_RECEIPT_IMAGES} multiple onChange={(event) => select(event, "gallery")} />
      </div>
      {pages.length > 0 && <div>
        <h3>Selected photos ({pages.length}/{MAX_RECEIPT_IMAGES})</h3>
        <p className="receipt-muted">For long receipts, add photos from top to bottom.</p>
        <ol className="receipt-photos">
          {pages.map((page, index) => <ReceiptPhoto key={page.id} page={page}
            index={index} onRotate={onRotate} onRemove={onRemove} />)}
        </ol>
      </div>}
    </div>
    <div className="receipt-scan-options">
      <label>Date format
        <select value={dateOrder} onChange={(event) => setDateOrder(event.target.value)}>
          <option value="DMY">Day / month / year</option><option value="MDY">Month / day / year</option>
        </select>
      </label>
      <label className="receipt-consent">
        <input type="checkbox" checked={allowAi} onChange={(event) => setAllowAi(event.target.checked)} />
        <span>Allow Gemini to help read this receipt
          <small>Shares filtered receipt text with Google for this scan. The photo stays on FinDash.</small>
        </span>
      </label>
    </div>
    <button className="dash-button dash-primary" type="submit" disabled={!pages.length}>Extract receipt</button>
  </form>;
}

ReceiptUpload.propTypes = { pages: PropTypes.arrayOf(pageType).isRequired,
  onFiles: PropTypes.func.isRequired, onRotate: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired, onScan: PropTypes.func.isRequired };
