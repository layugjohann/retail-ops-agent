# 02: All four Upload formats

**What to build:** Store inventory, Online Shop sales and Online Shop inventory Uploads are generated and accepted alongside Store sales. Online Shop sales arrive as an order-line export that has to be totalled to daily sales, excluding cancelled and refunded lines. The dashboard gains an inventory view.

**Blocked by:** 01
**Stacked on:** issue/01-walking-skeleton

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/2

- [ ] The generator produces all four formats from the spec (Store sales, Store inventory, Online Shop order lines with paid/cancelled/refunded, Online Shop stock snapshot with its own headers)
- [ ] Generated inventory is consistent with sales and with restocks arriving after the lead time
- [ ] Online Shop sales loaded through the Ops Day match the generator's internal daily totals, with cancelled and refunded lines excluded
- [ ] All four kinds are accepted for clean Uploads, and Upload status distinguishes sales from inventory
- [ ] The dashboard shows inventory by Sales Channel and SKU

## Comments

Usage: Implementer 42 input, 41,878 output, 95,908 cache creation, 1,619,786 cache read; Review Session 12 input, 4,118 output, 60,883 cache creation, 356,407 cache read.

**Review Session: Non-critical Findings**

- OpsDay.run_ops_day indexes channel_kinds[upload.sales_channel] directly; an Upload from the Data Source for an unknown Sales Channel (one not submitted through submit_upload) raises KeyError and aborts the whole Ops Day instead of being Quarantined or reported with a clear message.
- generator/history.py uses the GLOSSARY Avoid word 'run' (docstrings 'a run of days', variable `run`).
- Online Shop Order Lines check MAX_PLAUSIBLE_DAILY_UNITS per line only; the totalled daily quantity per SKU is never checked against it, so many paid lines can add up to an implausible daily sale without a Defect.
- _Row.sales_channel's Defect detail says 'store code ...', which reads like a general Sales Channel check but only fits the Store formats.
- OpsDay.inventory_by_sku silently falls back to the SKU code as the name and an empty category when a SKU is missing from the ERP.
- build_sandbox now sends both kinds of Upload for every Sales Channel, so the 14-day dashboard sandbox makes 196 Intake model calls (up from 84), which puts more pressure on free-tier rate limits with a real model.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-02-2026-11-18T06-40-48-275Z.log`).

Usage: Body writer 2 input, 1,629 output, 54,600 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/2

Stacked on Base Issue 01: this Pull Request targets `issue/01-walking-skeleton`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/1. Merge that Pull Request first.
