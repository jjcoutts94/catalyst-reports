"""
Catalyst Training Co — Combined Weekly Email Report
Pulls from Xero, Meta, and GymMaster with week-over-week
and month-over-month comparisons.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
from jinja2 import Template

from xero_report import get_weekly_report as get_xero_report
from meta_report import get_weekly_report as get_meta_report
from gymmaster_report import get_weekly_report as get_gym_report

load_dotenv()


# ──────────────────────────────────────────────
# Date helpers (Mon–Sun weeks)
# ──────────────────────────────────────────────

def _last_monday(dt):
    """Get the most recent Monday on or before dt."""
    return dt - timedelta(days=dt.weekday())


def get_periods():
    """Calculate reporting periods.

    When run on Monday morning (cron), "current week" = the just-completed
    Mon–Sun. Otherwise, current week = most recent Mon to today.
    """
    today = datetime.now().date()

    # If today is Monday, report on the PREVIOUS Mon–Sun (just completed)
    if today.weekday() == 0:  # Monday
        cw_end = today - timedelta(days=1)  # Sunday
        cw_start = cw_end - timedelta(days=6)  # Monday before
    else:
        cw_end = today
        cw_start = _last_monday(today)

    # Previous week = the Mon–Sun before current week
    pw_end = cw_start - timedelta(days=1)  # Sunday before
    pw_start = _last_monday(pw_end)

    # Current month = 1st of this month to today
    cm_start = today.replace(day=1)
    cm_end = today

    # Previous month
    pm_end = cm_start - timedelta(days=1)
    pm_start = pm_end.replace(day=1)

    return {
        "cw": (cw_start.isoformat(), cw_end.isoformat()),
        "pw": (pw_start.isoformat(), pw_end.isoformat()),
        "cm": (cm_start.isoformat(), cm_end.isoformat()),
        "pm": (pm_start.isoformat(), pm_end.isoformat()),
    }


def pct_change(current, previous):
    """Calculate percentage change. Returns None if previous is 0."""
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 1)


def delta_str(current, previous, is_money=False, invert=False):
    """Format a comparison string like '+12.5%' with arrow."""
    pct = pct_change(current, previous)
    if pct is None:
        return {"pct": None, "direction": "neutral", "arrow": "", "label": "N/A"}

    if pct > 0:
        direction = "negative" if invert else "positive"
        arrow = "&#9650;"  # ▲
    elif pct < 0:
        direction = "positive" if invert else "negative"
        arrow = "&#9660;"  # ▼
    else:
        direction = "neutral"
        arrow = "&#9644;"  # ▬

    diff = current - previous
    if is_money:
        diff_label = f"${abs(diff):,.0f}"
    else:
        diff_label = f"{abs(diff):,.0f}"

    return {
        "pct": pct,
        "direction": direction,
        "arrow": arrow,
        "label": f"{arrow} {abs(pct)}%",
        "diff": diff_label,
    }


# ──────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────

def fetch_all(start, end, label=""):
    """Fetch data from all three sources for a date range."""
    if label:
        print(f"  [{label}] {start} to {end}")

    try:
        xero = get_xero_report(start, end)
    except Exception as e:
        print(f"    Xero error: {e}")
        xero = {"revenue": 0, "expenses": 0, "net_position": 0,
                "revenue_breakdown": [], "expense_breakdown": []}

    try:
        meta = get_meta_report(start, end)
    except Exception as e:
        print(f"    Meta error: {e}")
        meta = {"total_spend": 0, "total_leads": 0, "overall_cpl": 0,
                "total_reach": 0, "total_impressions": 0, "total_clicks": 0,
                "campaigns": []}

    try:
        gym = get_gym_report(start, end)
    except Exception as e:
        print(f"    GymMaster error: {e}")
        gym = _empty_gym()

    return xero, meta, gym


def _empty_gym():
    return {
        "active_members": 0, "prospects_excl_fp": 0, "prospects_fp": 0,
        "prospect_names": [], "new_memberships": 0, "new_membership_list": [],
        "new_trials": 0, "trial_list": [], "class_count": 0,
        "class_avg_attendance": 0, "class_total_checkins": 0,
        "pt_sessions_total": 0, "pt_breakdown": [], "churned": 0,
        "churn_reasons": [], "churn_rate": 0, "revenue_total": 0,
        "revenue_by_type": {}, "failed_payments_count": 0,
        "failed_payments_amount": 0, "casual_sales": 0, "other_sales": 0,
    }


# ──────────────────────────────────────────────
# Email template
# ──────────────────────────────────────────────

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; margin: 0; padding: 20px; color: #1a1a1a; }
  .container { max-width: 700px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  .header { background: #1a1a1a; color: #ffffff; padding: 32px; text-align: center; }
  .header h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: 1px; }
  .header p { margin: 8px 0 0; font-size: 13px; opacity: 0.7; }
  .section { padding: 24px 32px; border-bottom: 1px solid #eee; }
  .section:last-child { border-bottom: none; }
  .section-title { font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #888; margin: 0 0 16px; }
  .sub-title { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #aaa; margin: 18px 0 10px; }
  .metric-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
  .metric-row:last-child { border-bottom: none; }
  .metric-label { font-size: 14px; color: #555; }
  .metric-value { font-size: 14px; font-weight: 600; color: #1a1a1a; }
  .positive { color: #16a34a; }
  .negative { color: #dc2626; }
  .neutral { color: #888; }
  .campaign-card { background: #f8f8f8; border-radius: 8px; padding: 14px; margin-bottom: 8px; }
  .campaign-name { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .campaign-stats { font-size: 12px; color: #666; }
  .kpi-grid { display: flex; gap: 10px; flex-wrap: wrap; }
  .kpi-box { flex: 1; min-width: 90px; background: #f8f8f8; border-radius: 8px; padding: 14px 10px; text-align: center; }
  .kpi-box .label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 4px; }
  .kpi-box .value { font-size: 20px; font-weight: 700; }
  .kpi-box .delta { font-size: 11px; margin-top: 4px; font-weight: 600; }
  .person-list { margin: 4px 0; padding: 0; list-style: none; }
  .person-list li { font-size: 13px; color: #555; padding: 3px 0; }
  .person-list li span { color: #aaa; font-size: 11px; }
  .footer { padding: 20px 32px; text-align: center; font-size: 11px; color: #aaa; }
  .comp-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; }
  .comp-label { font-size: 12px; color: #888; }
  .comp-value { font-size: 12px; font-weight: 600; }
  .period-tabs { display: flex; gap: 0; margin-bottom: 16px; }
  .period-tab { flex: 1; text-align: center; padding: 8px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #888; background: #f8f8f8; }
  .period-tab:first-child { border-radius: 6px 0 0 6px; }
  .period-tab:last-child { border-radius: 0 6px 6px 0; }
  .period-tab.active { background: #1a1a1a; color: #fff; }
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>CATALYST TRAINING CO</h1>
    <p>Weekly Performance Report &mdash; {{ cw_label }}</p>
  </div>

  <!-- ============ FINANCIALS ============ -->
  <div class="section">
    <div class="section-title">Financials</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Revenue</div>
        <div class="value positive">${{ "{:,.0f}".format(cw_xero.revenue) }}</div>
        <div class="delta {{ d_xero_rev.direction }}">{{ d_xero_rev.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Expenses</div>
        <div class="value">${{ "{:,.0f}".format(cw_xero.expenses) }}</div>
        <div class="delta {{ d_xero_exp.direction }}">{{ d_xero_exp.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Net Position</div>
        <div class="value {% if cw_xero.net_position >= 0 %}positive{% else %}negative{% endif %}">
          ${{ "{:,.0f}".format(cw_xero.net_position) }}
        </div>
        <div class="delta {{ d_xero_net.direction }}">{{ d_xero_net.label }} vs last wk</div>
      </div>
    </div>

    <!-- Month comparison -->
    <div class="sub-title">Month to Date vs Previous Month</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">MTD Revenue</div>
        <div class="value">${{ "{:,.0f}".format(cm_xero.revenue) }}</div>
        <div class="delta {{ dm_xero_rev.direction }}">{{ dm_xero_rev.label }} vs prev month</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Expenses</div>
        <div class="value">${{ "{:,.0f}".format(cm_xero.expenses) }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Net</div>
        <div class="value {% if cm_xero.net_position >= 0 %}positive{% else %}negative{% endif %}">${{ "{:,.0f}".format(cm_xero.net_position) }}</div>
      </div>
    </div>

    {% if cw_xero.revenue_breakdown %}
    <div class="sub-title">Revenue Breakdown (This Week)</div>
    {% for item in cw_xero.revenue_breakdown %}
    <div class="metric-row">
      <span class="metric-label">{{ item.name }}</span>
      <span class="metric-value">${{ "{:,.0f}".format(item.amount) }}</span>
    </div>
    {% endfor %}
    {% endif %}
  </div>

  <!-- ============ GYMMASTER REVENUE ============ -->
  <div class="section">
    <div class="section-title">GymMaster Revenue &amp; Payments</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Revenue</div>
        <div class="value positive">${{ "{:,.0f}".format(cw_gym.revenue_total) }}</div>
        <div class="delta {{ d_gym_rev.direction }}">{{ d_gym_rev.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Failed Payments</div>
        <div class="value negative">${{ "{:,.0f}".format(cw_gym.failed_payments_amount) }}</div>
        <div class="delta {{ d_gym_fail.direction }}">{{ d_gym_fail.label }} vs last wk</div>
      </div>
    </div>
    {% if cw_gym.revenue_by_type %}
    <div class="sub-title">Revenue by Type</div>
    {% for type, amount in cw_gym.revenue_by_type.items() %}
    <div class="metric-row">
      <span class="metric-label">{{ type }}</span>
      <span class="metric-value {% if amount < 0 %}negative{% endif %}">${{ "{:,.2f}".format(amount) }}</span>
    </div>
    {% endfor %}
    {% endif %}
  </div>

  <!-- ============ PROSPECTS & MEMBERSHIPS ============ -->
  <div class="section">
    <div class="section-title">Prospects &amp; Memberships</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Prospects</div>
        <div class="value">{{ cw_gym.prospects_excl_fp }}</div>
        <div class="delta {{ d_gym_prosp.direction }}">{{ d_gym_prosp.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">FP Prospects</div>
        <div class="value neutral">{{ cw_gym.prospects_fp }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">New Members</div>
        <div class="value positive">{{ cw_gym.new_memberships }}</div>
        <div class="delta {{ d_gym_memb.direction }}">{{ d_gym_memb.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Trials</div>
        <div class="value">{{ cw_gym.new_trials }}</div>
        <div class="delta {{ d_gym_trial.direction }}">{{ d_gym_trial.label }} vs last wk</div>
      </div>
    </div>

    <!-- Month comparison -->
    <div class="sub-title">Month to Date vs Previous Month</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">MTD Prospects</div>
        <div class="value">{{ cm_gym.prospects_excl_fp }}</div>
        <div class="delta {{ dm_gym_prosp.direction }}">{{ dm_gym_prosp.label }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Members</div>
        <div class="value">{{ cm_gym.new_memberships }}</div>
        <div class="delta {{ dm_gym_memb.direction }}">{{ dm_gym_memb.label }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Trials</div>
        <div class="value">{{ cm_gym.new_trials }}</div>
      </div>
    </div>

    {% if cw_gym.prospect_names %}
    <div class="sub-title">Prospects This Week (excl. Fitness Passport)</div>
    <ul class="person-list">
      {% for p in cw_gym.prospect_names %}
      <li>{{ p.name }} <span>{{ p.source }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cw_gym.new_membership_list %}
    <div class="sub-title">New Memberships This Week</div>
    <ul class="person-list">
      {% for m in cw_gym.new_membership_list %}
      <li>{{ m.name }} &mdash; {{ m.type }} @ {{ m.fee }}{% if m.rejoin %} <span>(Rejoin)</span>{% endif %}</li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if cw_gym.trial_list %}
    <div class="sub-title">Trials This Week</div>
    <ul class="person-list">
      {% for t in cw_gym.trial_list %}
      <li>{{ t.name }} &mdash; {{ t.type }}</li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>

  <!-- ============ CLASSES & TRAINING ============ -->
  <div class="section">
    <div class="section-title">Classes &amp; 1-on-1 Training</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Classes Run</div>
        <div class="value">{{ cw_gym.class_count }}</div>
        <div class="delta {{ d_gym_class.direction }}">{{ d_gym_class.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Avg Attendance</div>
        <div class="value">{{ cw_gym.class_avg_attendance }}</div>
        <div class="delta {{ d_gym_avg.direction }}">{{ d_gym_avg.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Check-ins</div>
        <div class="value">{{ cw_gym.class_total_checkins }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">PT Sessions</div>
        <div class="value">{{ cw_gym.pt_sessions_total }}</div>
        <div class="delta {{ d_gym_pt.direction }}">{{ d_gym_pt.label }} vs last wk</div>
      </div>
    </div>

    {% if cw_gym.pt_breakdown %}
    <div class="sub-title">PT Sessions by Trainer</div>
    {% for pt in cw_gym.pt_breakdown %}
    <div class="metric-row">
      <span class="metric-label">{{ pt.trainer }}</span>
      <span class="metric-value">{{ pt.sessions }} sessions <span style="font-size:11px;color:#aaa">({{ pt.no_shows }} no-shows)</span></span>
    </div>
    {% endfor %}
    {% endif %}
  </div>

  <!-- ============ CHURN ============ -->
  <div class="section">
    <div class="section-title">Retention &amp; Churn</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Active Members</div>
        <div class="value">{{ cw_gym.active_members }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">Churned</div>
        <div class="value negative">{{ cw_gym.churned }}</div>
        <div class="delta {{ d_gym_churn.direction }}">{{ d_gym_churn.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Churn Rate</div>
        <div class="value {% if cw_gym.churn_rate > 3 %}negative{% elif cw_gym.churn_rate > 1.5 %}{% else %}positive{% endif %}">{{ cw_gym.churn_rate }}%</div>
      </div>
    </div>

    <div class="sub-title">Month to Date vs Previous Month</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">MTD Churned</div>
        <div class="value negative">{{ cm_gym.churned }}</div>
        <div class="delta {{ dm_gym_churn.direction }}">{{ dm_gym_churn.label }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Churn Rate</div>
        <div class="value">{{ cm_gym.churn_rate }}%</div>
      </div>
    </div>

    {% if cw_gym.churn_reasons %}
    <div class="sub-title">Cancellations This Week</div>
    <ul class="person-list">
      {% for c in cw_gym.churn_reasons %}
      <li>{{ c.name }} &mdash; {{ c.type }} <span>{{ c.reason }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>

  <!-- ============ META ADS ============ -->
  <div class="section">
    <div class="section-title">Meta Ads</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">Ad Spend</div>
        <div class="value">${{ "{:,.0f}".format(cw_meta.total_spend) }}</div>
        <div class="delta {{ d_meta_spend.direction }}">{{ d_meta_spend.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Leads</div>
        <div class="value">{{ cw_meta.total_leads }}</div>
        <div class="delta {{ d_meta_leads.direction }}">{{ d_meta_leads.label }} vs last wk</div>
      </div>
      <div class="kpi-box">
        <div class="label">Cost/Lead</div>
        <div class="value">{% if cw_meta.overall_cpl > 0 %}${{ "{:,.2f}".format(cw_meta.overall_cpl) }}{% else %}&mdash;{% endif %}</div>
      </div>
      <div class="kpi-box">
        <div class="label">Reach</div>
        <div class="value">{{ "{:,}".format(cw_meta.total_reach) }}</div>
      </div>
    </div>

    <div class="sub-title">Month to Date</div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <div class="label">MTD Spend</div>
        <div class="value">${{ "{:,.0f}".format(cm_meta.total_spend) }}</div>
        <div class="delta {{ dm_meta_spend.direction }}">{{ dm_meta_spend.label }} vs prev month</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD Leads</div>
        <div class="value">{{ cm_meta.total_leads }}</div>
        <div class="delta {{ dm_meta_leads.direction }}">{{ dm_meta_leads.label }}</div>
      </div>
      <div class="kpi-box">
        <div class="label">MTD CPL</div>
        <div class="value">{% if cm_meta.overall_cpl > 0 %}${{ "{:,.2f}".format(cm_meta.overall_cpl) }}{% else %}&mdash;{% endif %}</div>
      </div>
    </div>

    {% if cw_meta.campaigns %}
    <div class="sub-title">Campaigns This Week</div>
    {% for c in cw_meta.campaigns %}
    <div class="campaign-card">
      <div class="campaign-name">{{ c.name }}</div>
      <div class="campaign-stats">
        ${{ "{:,.0f}".format(c.spend) }} spend &bull;
        {{ c.leads }} leads &bull;
        {% if c.cpl > 0 %}${{ "{:,.2f}".format(c.cpl) }} CPL &bull;{% endif %}
        {{ c.clicks }} clicks &bull;
        {{ "{:,}".format(c.reach) }} reach
      </div>
    </div>
    {% endfor %}
    {% else %}
    <p style="font-size: 13px; color: #aaa; margin-top: 12px;">No active campaigns this week.</p>
    {% endif %}
  </div>

  <div class="footer">
    Generated {{ generated_at }} &bull; Catalyst Training Co, Randwick NSW
  </div>

</div>
</body>
</html>
"""


# ──────────────────────────────────────────────
# Build + Send
# ──────────────────────────────────────────────

class DotDict(dict):
    __getattr__ = dict.__getitem__


def build_report():
    """Pull data for all four periods."""
    periods = get_periods()

    print("Pulling data for 4 periods...")
    cw_xero, cw_meta, cw_gym = fetch_all(*periods["cw"], "This Week")
    pw_xero, pw_meta, pw_gym = fetch_all(*periods["pw"], "Last Week")
    cm_xero, cm_meta, cm_gym = fetch_all(*periods["cm"], "This Month")
    pm_xero, pm_meta, pm_gym = fetch_all(*periods["pm"], "Prev Month")

    return {
        "cw": (cw_xero, cw_meta, cw_gym),
        "pw": (pw_xero, pw_meta, pw_gym),
        "cm": (cm_xero, cm_meta, cm_gym),
        "pm": (pm_xero, pm_meta, pm_gym),
        "periods": periods,
    }


def render_email(data):
    """Render the HTML email with comparisons."""
    cw_xero, cw_meta, cw_gym = data["cw"]
    pw_xero, pw_meta, pw_gym = data["pw"]
    cm_xero, cm_meta, cm_gym = data["cm"]
    pm_xero, pm_meta, pm_gym = data["pm"]
    periods = data["periods"]

    template = Template(EMAIL_TEMPLATE)
    return template.render(
        cw_label=f"{periods['cw'][0]} to {periods['cw'][1]}",
        generated_at=datetime.now().strftime("%d %b %Y at %I:%M %p"),

        # Current data (as DotDict for attribute access)
        cw_xero=DotDict(cw_xero),
        cw_meta=DotDict(cw_meta),
        cw_gym=DotDict(cw_gym),
        cm_xero=DotDict(cm_xero),
        cm_meta=DotDict(cm_meta),
        cm_gym=DotDict(cm_gym),

        # Week-over-week deltas — Financials
        d_xero_rev=delta_str(cw_xero["revenue"], pw_xero["revenue"], is_money=True),
        d_xero_exp=delta_str(cw_xero["expenses"], pw_xero["expenses"], is_money=True, invert=True),
        d_xero_net=delta_str(cw_xero["net_position"], pw_xero["net_position"], is_money=True),

        # Month-over-month — Financials
        dm_xero_rev=delta_str(cm_xero["revenue"], pm_xero["revenue"], is_money=True),

        # Week-over-week — GymMaster Revenue
        d_gym_rev=delta_str(cw_gym["revenue_total"], pw_gym["revenue_total"], is_money=True),
        d_gym_fail=delta_str(cw_gym["failed_payments_amount"], pw_gym["failed_payments_amount"], is_money=True, invert=True),

        # Week-over-week — Prospects & Memberships
        d_gym_prosp=delta_str(cw_gym["prospects_excl_fp"], pw_gym["prospects_excl_fp"]),
        d_gym_memb=delta_str(cw_gym["new_memberships"], pw_gym["new_memberships"]),
        d_gym_trial=delta_str(cw_gym["new_trials"], pw_gym["new_trials"]),

        # Month-over-month — Prospects & Memberships
        dm_gym_prosp=delta_str(cm_gym["prospects_excl_fp"], pm_gym["prospects_excl_fp"]),
        dm_gym_memb=delta_str(cm_gym["new_memberships"], pm_gym["new_memberships"]),

        # Week-over-week — Classes & PT
        d_gym_class=delta_str(cw_gym["class_count"], pw_gym["class_count"]),
        d_gym_avg=delta_str(cw_gym["class_avg_attendance"], pw_gym["class_avg_attendance"]),
        d_gym_pt=delta_str(cw_gym["pt_sessions_total"], pw_gym["pt_sessions_total"]),

        # Week-over-week — Churn (inverted: more churn = bad)
        d_gym_churn=delta_str(cw_gym["churned"], pw_gym["churned"], invert=True),

        # Month-over-month — Churn
        dm_gym_churn=delta_str(cm_gym["churned"], pm_gym["churned"], invert=True),

        # Week-over-week — Meta
        d_meta_spend=delta_str(cw_meta["total_spend"], pw_meta["total_spend"], is_money=True),
        d_meta_leads=delta_str(cw_meta["total_leads"], pw_meta["total_leads"]),

        # Month-over-month — Meta
        dm_meta_spend=delta_str(cm_meta["total_spend"], pm_meta["total_spend"], is_money=True),
        dm_meta_leads=delta_str(cm_meta["total_leads"], pm_meta["total_leads"]),
    )


def send_email(html_content):
    """Send the report via Gmail SMTP."""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipients = os.getenv("EMAIL_RECIPIENTS", "").split(",")
    recipients = [r.strip() for r in recipients if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Catalyst Weekly Report — {datetime.now().strftime('%d %b %Y')}"
    msg["From"] = f"Catalyst Reports <{sender}>"
    msg["To"] = ", ".join(recipients)

    plain = "Catalyst Training Co — Weekly Report\nView this email in HTML for the full report.\n"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())

    print(f"Report sent to {', '.join(recipients)}")


def main():
    """Build and send the weekly report."""
    print("=" * 55)
    print(" CATALYST TRAINING CO — WEEKLY REPORT")
    print("=" * 55)

    data = build_report()
    html = render_email(data)

    # Save a local copy
    output_path = os.path.join(
        os.path.dirname(__file__),
        f"report_{datetime.now().strftime('%Y%m%d')}.html",
    )
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Saved local copy: {output_path}")

    send_email(html)
    print("Done!")


if __name__ == "__main__":
    main()
