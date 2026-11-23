export const notificationPath = "/api/notifications/";

export const categories = {
  budget_threshold: { label: "Budget thresholds", description: "When spending reaches a budget alert threshold." },
  subscription_renewal: { label: "Subscription renewals", description: "Upcoming renewals when reminders are enabled in Subscriptions." },
  unusual_spending: { label: "Unusual spending", description: "When a transaction stands out from your recent spending." },
  statement_import: { label: "Statement imports", description: "When a bank statement import completes." },
  financial_report: { label: "Financial reports", description: "When a financial report is generated." },
  grocery_deal: { label: "Grocery deals", description: "When a catalog refresh finds an advertised offer for a product with alerts enabled." },
  warranty_expiration: { label: "Warranty expiration", description: "When a warranty reaches one of your selected reminder dates." },
  stock_threshold: { label: "Stock price thresholds", description: "When a fresh quote meets a watchlist price rule and market checks are enabled." },
};

export function startNotificationPolling({
  load, onData, onError, canPoll, setTimer = setTimeout, clearTimer = clearTimeout,
  interval = 30_000, retryInterval = 5_000, maxRetryInterval = 120_000,
}) {
  let stopped = false;
  let pending;
  let timer;
  let failures = 0;

  function pause() {
    clearTimer(timer);
    pending?.abort();
    pending = undefined;
  }

  async function refresh() {
    if (stopped || pending || !canPoll()) return;
    clearTimer(timer);
    const controller = new AbortController();
    pending = controller;
    let wait = interval;
    try {
      const data = await load(controller.signal);
      if (controller.signal.aborted) return;
      failures = 0;
      onData(data);
    } catch (error) {
      if (controller.signal.aborted) return;
      const status = error.response?.status;
      failures += 1;
      wait = Math.min(maxRetryInterval, retryInterval * 2 ** Math.min(failures - 1, 10));
      if (status === 401 || status === 403 || status === 429) wait = maxRetryInterval;
      onError(error);
    } finally {
      if (pending === controller) {
        pending = undefined;
        if (canPoll()) timer = setTimer(refresh, wait);
      }
    }
  }

  function resync() {
    if (canPoll()) refresh();
    else pause();
  }

  resync();
  return {
    refresh,
    resync,
    stop() {
      stopped = true;
      pause();
    },
  };
}
