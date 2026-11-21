import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Navigate } from "react-router-dom";
import { jwtDecode } from "jwt-decode";
import { refreshSession } from "../api";
import { ACCESS_TOKEN } from "../constants";

function ProtectedRoute({ children }) {
  const [isAuthorized, setIsAuthorized] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    async function authorize() {
      try {
        const token = localStorage.getItem(ACCESS_TOKEN);
        if (!token) {
          setIsAuthorized(false);
          return;
        }
        if (jwtDecode(token).exp < Date.now() / 1000) {
          const renewed = await refreshSession(token);
          if (!controller.signal.aborted) setIsAuthorized(Boolean(renewed));
          return;
        }
        setIsAuthorized(true);
      } catch {
        if (!controller.signal.aborted) setIsAuthorized(false);
      }
    }

    authorize();
    return () => controller.abort();
  }, []);

  if (isAuthorized === null) return <div>Loading...</div>;
  return isAuthorized ? children : <Navigate to="/login" />;
}

ProtectedRoute.propTypes = { children: PropTypes.node.isRequired };

export default ProtectedRoute;
