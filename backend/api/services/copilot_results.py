from decimal import Decimal


def observed(record):
    category = record.get("category")
    label = f"Net spending on {category}" if category else "Net spending"
    totals = [row for row in record["totals"] if row["transaction_count"]]
    if not totals:
        if record["totals"] and category and not record["truncated"]:
            return f"No {category} spending or refunds were recorded in this period."
        return "There are no recorded spending or refund entries for this selection."
    lines = [f"{label} from {record['start_date']} through {record['end_date']}:"]
    for row in totals:
        currency = row["currency"]
        lines.append(f"{currency} {row['net_spending']} across {row['transaction_count']} entries.")
        if row.get("categories"):
            top = sorted(row["categories"].items(), key=lambda item: Decimal(item[1]), reverse=True)[:3]
            lines.append("Leading categories: " + ", ".join(f"{name} {currency} {value}" for name, value in top) + ".")
    return "\n".join(lines)


def comparison(record):
    if not record["totals"]:
        return "Neither period contains recorded spending or refunds."
    first, second = record["period_a"], record["period_b"]
    lines = [f"Net spending from {first[0]} through {first[1]} versus {second[0]} through {second[1]}:"]
    for row in record["totals"]:
        currency = row["currency"]
        if not row["period_a_count"] or not row["period_b_count"]:
            known = row["period_a_net_spending"] if row["period_a_count"] else row["period_b_net_spending"]
            period = "second" if row["period_a_count"] else "first"
            lines.append(f"{currency} {known} was recorded in the other period. The {period} period has no {currency} entries to compare.")
            continue
        lines.append(f"{currency} {row['period_a_net_spending']} → {row['period_b_net_spending']} "
                     f"(change {row['change_b_minus_a']}).")
        increase = record["largest_category_increases"].get(currency)
        lines.append(
            f"Largest category increase: {increase['category']} ({currency} {increase['change']})."
            if increase else f"No {currency} category increased."
        )
    return "\n".join(lines)


def budgets(record):
    if not record["budgets"]:
        return "There are no active budgets for this month."
    lines = [f"Budget progress for {record['month']} through {record['as_of']}:"]
    for row in sorted(record["budgets"], key=lambda item: Decimal(item["percentage_used"]), reverse=True):
        used = Decimal(row["percentage_used"])
        remaining = Decimal(row["remaining"])
        if remaining < 0:
            state = "Over limit"
        elif remaining == 0:
            state = "At limit"
        else:
            state = "Close to limit" if used >= 80 else "Within limit"
        lines.append(f"{row['category'] or 'Overall'}: {state} · {row['percentage_used']}% used "
                     f"({row['currency']} {row['actual_spending']} of {row['limit']}).")
    return "\n".join(lines)


def subscriptions(record):
    if not record["totals"]:
        return "There are no confirmed active subscriptions to estimate."
    lines = ["Estimated costs for active confirmed subscriptions:"]
    for row in record["totals"]:
        currency = row["currency"]
        lines.append(f"{currency} {row['estimated_monthly']} monthly and {row['estimated_annual']} yearly.")
        largest = [item for item in record["largest_recurring_expenses"] if item["currency"] == currency]
        if largest:
            lines.append("Largest recurring expenses: " + ", ".join(
                f"{item['merchant']} ({currency} {item['amount']} {item['frequency']})" for item in largest
            ) + ".")
    return "\n".join(lines)


def recent(record):
    rows = record["transactions"]
    if not rows:
        return "There are no recent transactions to show."
    return "Recent transactions (signed amounts):\n" + "\n".join(
        f"{row['date']} · {row['category']} · {row['currency']} {row['signed_amount']}" for row in rows
    )


RENDER = {
    "get_category_breakdown": observed,
    "get_spending_summary": observed,
    "compare_spending_periods": comparison,
    "get_budget_status": budgets,
    "get_subscription_summary": subscriptions,
    "get_recent_transactions": recent,
}


def date_ranges(record):
    if "start_date" in record:
        return [(record["start_date"], record["end_date"])]
    if "period_a" in record:
        return [tuple(record["period_a"]), tuple(record["period_b"])]
    if "month" in record:
        return [(record["month"] + "-01", record["as_of"])]
    if record.get("transactions"):
        dates = [row["date"] for row in record["transactions"]]
        return [(min(dates), max(dates))]
    return []


def visualization(record, index):
    if record.get("largest_category_increases") is not None and any(
        row["period_a_count"] and row["period_b_count"] for row in record["totals"]
    ):
        return {"type": "period_comparison", "metric_index": index}
    if any(row.get("categories") for row in record.get("totals", [])):
        return {"type": "category_breakdown", "metric_index": index}
    return None


def build_result(records):
    text = []
    ranges = {}
    chart = None
    for index, record in enumerate(records):
        text.append(record["error"] if "error" in record else RENDER[record["tool"]](record))
        if record.get("truncated"):
            text.append("Results show a limited set of currencies or records.")
        for start, end in date_ranges(record):
            ranges[start, end] = {"start_date": start, "end_date": end}
        chart = chart or visualization(record, index)

    return {
        "answer": "\n\n".join(text) or "I don’t have enough information to calculate that. Try specifying a period, category, or financial activity.",
        "metrics": records,
        "date_ranges": list(ranges.values()),
        "visualization": chart,
    }
