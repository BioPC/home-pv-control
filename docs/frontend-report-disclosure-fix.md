# Reports disclosure presentation correction

Observed in actual HA 2025.12.0 and 2026.10.4 captures from browser run
40893052260 on commit 555dd0c2a94f4f91b58684a57118d5963b827352:
closed report summaries had disclosure arrows but their body text remained
visible outside the disclosure. The existing browser check of the `open`
attribute did not detect that rendering defect.

The Reports generator now emits each disclosure as one HTML block containing
escaped paragraph labels and values. It avoids blank-line Markdown bodies that
HA processes separately from the opening details element. Executive Summary
remains initially open; the other nine sections remain initially closed.
Report data generation, controls, HBC, policy and physical authorization are
unchanged. No control source or control regression test is modified.

The generated dashboard and its structure/hash records are regenerated to match
this UI-only correction. The preservation fixture changes only the generated
dashboard hash; all other preserved hashes retain their baseline values.
The browser test now checks actual paragraph containment, hidden/visible states
and expansion/collapse for all nine closed sections. Browser and complete
regression matrix results must still pass before visual approval.

## HBC sub-strategy binding correction

The actual native captures also showed the HBC sub-strategy row displaying the
overall HPVC status instead of the external HBC sub-strategy. The source row used
`simple-entity`, which was not converted to an attribute row for projected data.
Convert that row kind to the same readonly attribute presentation as other
projection rows. This changes display bindings only; it does not change the HBC
state reader, strategy selection, policy or any write path. The real-browser
fixture now asserts that the displayed sub-strategy is `Balanced`.

## Control-history legend clipping

After waiting for actual ApexCharts data idle, HA 2026.10.4 browser geometry
showed legend items extending to 483.8 pixels inside a 437.3-pixel card. Bound
the legend width to 280 pixels, omit redundant latest-value labels from that
legend, and shorten the executed-mode key while retaining all three mode names
and numeric mappings. Existing state rows and tooltips retain their values;
unknown data, cooldown/settling and all historical samples remain unchanged.
The browser test rejects legend items outside the card at every tested width.
