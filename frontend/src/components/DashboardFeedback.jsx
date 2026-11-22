import PropTypes from "prop-types";

export function DashboardLoading({ label = "Loading dashboard" }) {
  return <div className="dash-loading" role="status" aria-label={label}>
    <span /><span /><span />
  </div>;
}

export function DashboardError({ children, onRetry }) {
  return <div className="dash-error">
    <p role="alert">{children}</p><button type="button" className="dash-button" onClick={onRetry}>Retry</button>
  </div>;
}

DashboardLoading.propTypes = { label: PropTypes.string };
DashboardError.propTypes = { children: PropTypes.node.isRequired, onRetry: PropTypes.func.isRequired };
