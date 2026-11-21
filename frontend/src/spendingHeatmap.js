export function calendarDate(value) {
  return new Date(`${value}T00:00:00Z`);
}

export function summarizeHeatmap(days, category) {
  const offset = days.length ? calendarDate(days[0].date).getUTCDay() : 0;
  const months = Array(12).fill(0);
  let peak = null;
  let hasActivity = false;
  const cells = days.map((day, index) => {
    const amount = category ? day.category_totals[category] ?? 0 : day.total_spending;
    const count = category ? day.category_counts[category] ?? 0 : day.transaction_count;
    const cents = Math.round(Number(amount) * 100);
    const month = Number(day.date.slice(5, 7)) - 1;
    const position = offset + index;
    const cell = {
      date: day.date,
      cents,
      count,
      month,
      week: Math.floor(position / 7),
      weekday: position % 7,
    };
    months[month] += cents;
    hasActivity ||= count > 0;
    if (cents > (peak?.cents ?? 0)) peak = cell;
    return cell;
  });
  return { cells, months, peak, hasActivity };
}

export function intensity(cents, peak) {
  if (cents <= 0 || peak <= 0) return 0;
  return Math.min(4, Math.ceil((cents / peak) * 4));
}

export function spendingBands(peak) {
  return Array.from({ length: 4 }, (_, index) => ({
    level: index + 1,
    min: Math.floor((peak * index) / 4) + 1,
    max: Math.floor((peak * (index + 1)) / 4),
  })).filter(({ min, max }) => min <= max);
}

export function nextCellIndex(key, index, weekday, length) {
  const offsets = {
    ArrowUp: -1, ArrowDown: 1, ArrowLeft: -7, ArrowRight: 7,
    Home: -weekday, End: 6 - weekday,
  };
  if (!Object.hasOwn(offsets, key)) return null;
  const next = index + offsets[key];
  if (key === "Home" || key === "End") return Math.max(0, Math.min(length - 1, next));
  if ((key === "ArrowUp" && weekday === 0) || (key === "ArrowDown" && weekday === 6)) return index;
  return next >= 0 && next < length ? next : index;
}
