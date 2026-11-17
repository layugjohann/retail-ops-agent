# 02: All four Upload formats

**What to build:** Store inventory, Online Shop sales and Online Shop inventory Uploads are generated and accepted alongside Store sales. Online Shop sales arrive as an order-line export that has to be totalled to daily sales, excluding cancelled and refunded lines. The dashboard gains an inventory view.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The generator produces all four formats from the spec (Store sales, Store inventory, Online Shop order lines with paid/cancelled/refunded, Online Shop stock snapshot with its own headers)
- [ ] Generated inventory is consistent with sales and with restocks arriving after the lead time
- [ ] Online Shop sales loaded through the Ops Day match the generator's internal daily totals, with cancelled and refunded lines excluded
- [ ] All four kinds are accepted for clean Uploads, and Upload status distinguishes sales from inventory
- [ ] The dashboard shows inventory by Sales Channel and SKU

## Comments
