# 26: The Analyst compares a day's sales with its usual rate

**What to build:** A Stockout Risk's `average_daily_units` covers the whole 14-day window, the Anomaly's own day included. The Analyst then compares that day's sales with an average that already contains them. In the recorded Ops Day 02 it wrote "24 units sold on 2026-03-10, whereas the average daily sales over the past 9 days is only 3.67 units", but without the spike day the usual rate is about 1 unit a day.

Give the Stockout Risk a `usual_daily_units`: the average over the window's sales days before the Anomaly's day. Detection and days of cover stay as they are, because a spike is real demand and should still count toward cover. Tell the Analyst which average includes the day, then re-record the Ops Days.

**Blocked by:** 24 (the re-recording shares the Groq free-tier quota with Issue 24's eval run)

**Status:** ready-for-agent

## Acceptance criteria

- [ ] A Stockout Risk carries `usual_daily_units`, the average over its window's sales days before the Anomaly's day
- [ ] Its summary gives both rates
- [ ] The Analyst's instructions say `average_daily_units` includes the Anomaly's day and `usual_daily_units` does not
- [ ] The Ops Days are re-recorded, and their evidence compares a day's sales with the usual rate

## Comments
