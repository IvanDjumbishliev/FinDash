from html import escape
from io import BytesIO

import pymupdf

STYLES = """
body { font-family: sans-serif; color: #172036; font-size: 10pt; }
h1 { color: #34219b; font-size: 26pt; margin-bottom: 6pt; }
h2 { font-size: 14pt; color: #34219b; margin-top: 17pt; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; border: 1px solid #dce0eb; padding: 5pt; overflow-wrap: anywhere; }
th { background-color: #eeebff; }
small { color: #4d5870; }
"""


def table(headers, rows, empty):
    if not rows:
        return f"<p>{escape(empty)}</p>"
    head = "".join(f"<th>{escape(label)}</th>" for label in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value if value is not None else 'Unavailable'))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_report_pdf(report):
    period = report["period"]
    comparison = report["comparison"]
    previous = comparison["period"]
    activity = report["activity"]
    subscription = report["subscriptions"]
    ai = report["ai"]
    currency = report["currency"]
    monthly_rows = [
        ("Income", activity["income"]), ("Gross expenses", activity["gross_expenses"]),
        ("Refunds", activity["refunds"]), ("Net expenses", activity["net_expenses"]),
        ("Net cash flow", activity["net_cash_flow"]),
    ]
    subscription_totals = subscription["totals"]
    subscription_rows = [
        (subscription_totals["subscription_count"], subscription_totals["estimated_monthly"],
         subscription_totals["estimated_annual"])
    ] if subscription_totals else []
    overview_note = "" if activity["transaction_count"] else "<p>No qualifying transactions were recorded for this period and currency.</p>"
    ai_section = ""
    if ai["text"]:
        ai_section = (
            f"<h2>AI trend interpretation</h2><p>{escape(ai['text'])}</p>"
            f"<small>{escape(ai['notice'])}</small>"
        )
    elif ai["status"] != "not_requested":
        ai_section = "<h2>AI trend interpretation</h2><p>Commentary was unavailable for this report.</p>"
    content = f"""
    <h1>FinDash Financial Report</h1>
    <p><strong>{escape(period['start_date'])} to {escape(period['end_date'])}</strong>
       {' (month to date)' if period['partial'] else ''} | {escape(currency)} | {escape(report['timezone'])}</p>
    <p><small>Generated {escape(report['generated_at'])}</small></p>
    <h2>Monthly activity</h2>
    {overview_note}
    {table(('Measure', currency), monthly_rows, '')}
    <h2>Previous month comparison</h2>
    <p>{escape(previous['start_date'])} to {escape(previous['end_date'])}</p>
    {table(('Previous net expenses', 'Change in net expenses'), [(comparison['net_expenses'], comparison['change'])], '')}
    <h2>Category breakdown</h2>
    {table(('Category', 'Net expenses', 'Previous', 'Change'), [
        (item['category'], item['net_expenses'], item['previous_net_expenses'], item['change'])
        for item in report['categories']
    ], 'No category spending recorded.')}
    <h2>Largest expenses</h2>
    {table(('Date', 'Expense', 'Category', 'Amount'), [
        (item['date'], item['label'], item['category'], item['amount']) for item in report['largest_expenses']
    ], 'No expenses recorded.')}
    <h2>Budget performance</h2>
    {table(('Budget', 'Limit', 'Actual', 'Remaining', 'Used'), [
        (item['category'] or 'Overall', item['amount'], item['actual_spending'], item['remaining'],
         item['percentage_used'] + '%') for item in report['budgets']
    ], 'No active budgets for this month and currency.')}
    <h2>Subscription summary</h2>
    <p><small>Active confirmed subscriptions as of {escape(subscription['as_of'])}. Costs are estimates.</small></p>
    {table(('Subscriptions', 'Estimated monthly', 'Estimated annual'), subscription_rows, 'No active confirmed subscriptions in this currency.')}
    {table(('Largest recurring expense', 'Billing frequency', 'Charge estimate'), [
        (item['merchant'], item['frequency'], item['amount'])
        for item in subscription['largest_recurring_expenses']
    ], '') if subscription['largest_recurring_expenses'] else ''}
    <h2>Financial goals</h2>
    <p>{escape(report['goals']['message'])}</p>
    {ai_section}
    """
    page = pymupdf.paper_rect("a4")
    box = pymupdf.Rect(42, 40, page.width - 42, page.height - 40)
    output = BytesIO()
    with pymupdf.DocumentWriter(output) as writer:
        pymupdf.Story(content, user_css=STYLES).write(writer, lambda *_: (page, box, None))
    return output.getvalue()
