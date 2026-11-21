import { createContext, useContext, useEffect, useRef, useState } from "react";
import { jwtDecode } from "jwt-decode";
import api from "../api";
import { ACCESS_TOKEN } from "../constants";
import { notificationPath, startNotificationPolling } from "../notifications";

export const InboxContext = createContext(null);

export function notificationAccount() {
  try {
    return jwtDecode(localStorage.getItem(ACCESS_TOKEN)).user_id ?? null;
  } catch {
    return null;
  }
}

export function useNotificationInbox() {
  return useContext(InboxContext);
}

export function useNotificationQuery({ limit, offset = 0, category = "", unread = false, dismissed = false }) {
  const { account, revision } = useNotificationInbox();
  const key = JSON.stringify([account, limit, offset, category, unread, dismissed]);
  const [state, setState] = useState(null);
  const [offline, setOffline] = useState(() => navigator.onLine === false);
  const refresh = useRef(null);
  useEffect(() => {
    if (account === null) return;
    const canPoll = () => document.visibilityState !== "hidden" && navigator.onLine !== false && notificationAccount() === account;
    const polling = startNotificationPolling({
      canPoll,
      load: async (signal) => {
        const token = localStorage.getItem(ACCESS_TOKEN);
        const { data } = await api.get(notificationPath, {
          signal, timeout: 8_000, headers: { Authorization: `Bearer ${token}` },
          params: { limit, offset, category: category || undefined, unread, include_dismissed: dismissed },
        });
        return data;
      },
      onData: (data) => {
        if (canPoll()) setState({ key, data, error: false });
      },
      onError: (error) => {
        const unauthenticated = [401, 403].includes(error.response?.status);
        if (canPoll()) setState((previous) => ({
          key, error: true, data: !unauthenticated && previous?.key === key ? previous.data : null,
        }));
      },
    });
    refresh.current = polling.refresh;
    function resync() {
      setOffline(navigator.onLine === false);
      polling.resync();
    }
    document.addEventListener("visibilitychange", resync);
    for (const event of ["online", "offline", "focus", "pageshow"]) window.addEventListener(event, resync);
    return () => {
      polling.stop();
      refresh.current = null;
      document.removeEventListener("visibilitychange", resync);
      for (const event of ["online", "offline", "focus", "pageshow"]) window.removeEventListener(event, resync);
    };
  }, [account, revision, key, limit, offset, category, unread, dismissed]);

  return {
    data: state?.key === key && notificationAccount() === account ? state.data : null,
    error: state?.key === key && state.error,
    offline,
    retry: () => refresh.current?.(),
  };
}

