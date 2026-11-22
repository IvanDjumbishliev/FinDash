import { Component } from "react";
import PropTypes from "prop-types";

export default class PageBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    const { children, message } = this.props;
    if (!this.state.failed) return children;
    return <section className="dashboard-shell">
      <div className="dash-panel dash-error">
        <p role="alert">{message}</p>
        <button type="button" className="dash-button" onClick={() => window.location.reload()}>Reload page</button>
      </div>
    </section>;
  }
}

PageBoundary.propTypes = { children: PropTypes.node.isRequired, message: PropTypes.string.isRequired };
