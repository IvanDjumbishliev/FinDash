export const widgets = [
  { id: "monthly", label: "Monthly cash flow", default: true },
  { id: "overview", label: "Financial overview", default: true },
  { id: "budgets", label: "Budgets", default: true },
  { id: "subscriptions", label: "Upcoming subscriptions", default: true },
  { id: "goals", label: "Financial goals", default: true },
  { id: "insights", label: "Financial insights", default: true },
  { id: "heatmap", label: "Spending heatmap", default: true, separate: true },
  { id: "forecast", label: "Cash flow forecast", separate: true },
  { id: "portfolio", label: "Virtual portfolio" },
  { id: "deals", label: "Shopping deals" },
];

export const defaultWidgets = widgets.filter((widget) => widget.default).map(({ id }) => id);

export function readWidgets(storage, account) {
  try {
    const saved = JSON.parse(storage.getItem(`findash-dashboard:${account}`));
    if (Array.isArray(saved)) return widgets.filter(({ id }) => saved.includes(id)).map(({ id }) => id);
  } catch {
    // Preferences remain usable when browser storage is blocked.
  }
  return defaultWidgets;
}

export function saveWidgets(storage, account, visible) {
  storage.setItem(`findash-dashboard:${account}`, JSON.stringify(visible));
}

export function dashboardSections(visible) {
  return widgets.filter(({ id, separate }) => visible.includes(id) && !separate).map(({ id }) => id).join(",");
}
