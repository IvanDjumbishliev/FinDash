import PropTypes from "prop-types";

export const dealItems = PropTypes.arrayOf(PropTypes.shape({
  name: PropTypes.string.isRequired,
  price: PropTypes.string,
  image_url: PropTypes.string,
  price_note: PropTypes.string,
  storeName: PropTypes.string,
  discount_percent: PropTypes.number,
}));

export const storeList = PropTypes.arrayOf(PropTypes.shape({
  id: PropTypes.string.isRequired,
  name: PropTypes.string.isRequired,
  image: PropTypes.string.isRequired,
  offerUrl: PropTypes.string,
}));

export const dealResults = PropTypes.objectOf(PropTypes.shape({
  items: dealItems,
  error: PropTypes.bool,
}));
