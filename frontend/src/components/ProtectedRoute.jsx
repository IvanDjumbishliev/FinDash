import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { Navigate } from "react-router-dom";
import { jwtDecode } from "jwt-decode";
import api from "../api";
import { REFRESH_TOKEN, ACCESS_TOKEN } from "../constants";

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
          const refresh = localStorage.getItem(REFRESH_TOKEN);
          const response = await api.post("/api/token/refresh/", { refresh }, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (response.status !== 200) {
            setIsAuthorized(false);
            return;
          }
          localStorage.setItem(ACCESS_TOKEN, response.data.access);
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
