# 26: The Analyst compares a day's sales with its usual rate

**What to build:** A Stockout Risk's `average_daily_units` covers the whole 14-day window, the Anomaly's own day included. The Analyst then compares that day's sales with an average that already contains them. In the recorded Ops Day 02 it wrote "24 units sold on 2026-03-10, whereas the average daily sales over the past 9 days is only 3.67 units", but without the spike day the usual rate is about 1 unit a day.

Give the Stockout Risk a `usual_daily_units`: the average over the window's sales days before the Anomaly's day. Detection and days of cover stay as they are, because a spike is real demand and should still count toward cover. Tell the Analyst which average includes the day, then re-record the Ops Days.

**Blocked by:** 24 (the re-recording shares the Groq free-tier quota with Issue 24's eval run)

**Status:** done

## Acceptance criteria

- [x] A Stockout Risk carries `usual_daily_units`, the average over its window's sales days before the Anomaly's day
- [x] Its summary gives both rates
- [x] The Analyst's instructions say `average_daily_units` includes the Anomaly's day and `usual_daily_units` does not
- [x] The Ops Days are re-recorded, and their evidence compares a day's sales with the usual rate

## Comments

Re-recorded on `groq:openai/gpt-oss-120b`. The first re-record showed the new line alone made the Analyst call the surge's first day a one-off, so Ops Days 02 and 03 sent an Alert instead of a Reorder. The Analyst's instructions now also say a spike is real demand that counts toward cover. Ops Day 02's evidence now reads "Usual daily sales (excluding the spike): 1.12 units per day" and works out days of cover from 3.67.
