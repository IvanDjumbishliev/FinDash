import PropTypes from "prop-types";
import { FiHeart, FiPlus, FiVolumeX } from "react-icons/fi";
import { ProductImage, RetailerMark } from "../GroceryBasketResults";
import { displayDate, money } from "../../copilotPresentation";
import { offerExplanation, pricePerUnit } from "../../personalizedDeals";
import { receiptDate } from "../../receiptScanner";

const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Sofia",
});

export default function DealCard({ offer, favorite, added, muteName, preferredStores, busy, onAdd, onFavorite, onMute, onReview }) {
  const { currency, unit, historical } = offer;
  const difference = Number(historical?.difference);
  const uncertain = offer.relation === "needs_review";
  const label = uncertain ? "Needs review" : offer.relation === "exact" ? "Exact match" : "Comparable alternative";

  return <article className="my-deal-card" aria-label={`${offer.product_name} at ${offer.retailer}`}>
    <div className="my-deal-card-head">
      <ProductImage key={offer.image_url} src={offer.image_url} />
      <div><RetailerMark id={offer.retailer} /><h3>{offer.product_name}</h3>
        {offer.brand && <p className="my-deals-muted">{offer.brand}</p>}
      </div>
    </div>
    <dl className="my-deal-price">
      <div><dt>Advertised price</dt><dd>{money(offer.price, currency)}</dd></div>
      <div><dt>Unit price</dt><dd>{pricePerUnit(offer.unit_price, currency, unit)}</dd></div>
    </dl>
    <p className="my-deals-muted">Ends {offer.expires_at ? `${dateTime.format(new Date(offer.expires_at))} (Sofia)` : displayDate(offer.expires_on)}</p>
    {(offer.discount_percent > 0 || offer.requires_membership) && <p className="my-deals-muted">
      {[offer.discount_percent > 0 ? `Retailer advertises ${offer.discount_percent}% off` : null,
        offer.requires_membership ? "Membership required" : null].filter(Boolean).join(" · ")}
    </p>}
    {historical && !uncertain && <div className="my-deal-history">
      <strong>Historical price comparison</strong>
      <p>Paid {pricePerUnit(historical.unit_price, currency, unit)} on {receiptDate(historical.purchased_at)}.</p>
      {difference > 0 && <p>{pricePerUnit(historical.difference, currency, unit)} below that receipt price.</p>}
      {difference < 0 && <p>{pricePerUnit(-difference, currency, unit)} above that receipt price.</p>}
      {difference === 0 && <p>Same unit price as that receipt.</p>}
    </div>}
    <details className="my-deal-explanation">
      <summary>Why this deal matches</summary>
      <p><strong>{label}</strong> · {Math.round(Number(offer.confidence) * 100)}% match confidence</p>
      <ul>{offerExplanation(offer, preferredStores).map((reason) => <li key={reason}>{reason}</li>)}</ul>
    </details>
    <div className="dash-actions my-deal-actions">
      {uncertain ? <>
        <button type="button" className="dash-button" disabled={busy} onClick={() => onReview("accept")}>Accept as comparable</button>
        <button type="button" className="dash-button" disabled={busy} onClick={() => onReview("reject")}>Reject match</button>
      </> : <>
        <button type="button" className="dash-button dash-primary" disabled={busy || added || offer.requires_membership}
          onClick={onAdd}><FiPlus aria-hidden="true" /> {added ? "In shopping list" : "Add to shopping list"}</button>
        <button type="button" className="dash-button" disabled={busy || favorite} onClick={onFavorite}>
          <FiHeart aria-hidden="true" /> {favorite ? "Favorited" : "Save favorite"}
        </button>
      </>}
      <button type="button" className="dash-button" disabled={busy} onClick={onMute}>
        <FiVolumeX aria-hidden="true" /> Mute {muteName}
      </button>
    </div>
    {offer.requires_membership && <p className="my-deals-muted">The optimizer compares publicly available prices.</p>}
  </article>;
}

DealCard.propTypes = {
  offer: PropTypes.shape({
    image_url: PropTypes.string, retailer: PropTypes.string.isRequired, product_name: PropTypes.string.isRequired,
    brand: PropTypes.string, currency: PropTypes.string.isRequired, price: PropTypes.string.isRequired,
    unit: PropTypes.string.isRequired, unit_price: PropTypes.string.isRequired, expires_on: PropTypes.string.isRequired,
    expires_at: PropTypes.string, relation: PropTypes.string.isRequired, confidence: PropTypes.string.isRequired,
    discount_percent: PropTypes.number, requires_membership: PropTypes.bool.isRequired,
    historical: PropTypes.shape({ difference: PropTypes.string.isRequired, purchased_at: PropTypes.string.isRequired,
      unit_price: PropTypes.string.isRequired }),
    interest: PropTypes.shape({ name: PropTypes.string.isRequired }).isRequired,
  }).isRequired,
  muteName: PropTypes.string.isRequired, favorite: PropTypes.bool.isRequired, added: PropTypes.bool.isRequired, busy: PropTypes.bool.isRequired,
  preferredStores: PropTypes.arrayOf(PropTypes.string).isRequired,
  onAdd: PropTypes.func.isRequired, onFavorite: PropTypes.func.isRequired, onMute: PropTypes.func.isRequired,
  onReview: PropTypes.func.isRequired,
};
