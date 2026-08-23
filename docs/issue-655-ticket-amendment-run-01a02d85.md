# Issue #655 ticket amendment — judge run 01a02d85

Applied to the canonical GitHub issue on 2026-08-23; no runtime code changed.

1. Replaced the stale `错杀能吏→#479 寒心接口预留` wording with `错杀能吏→#479 寒心经 #633 结算口真入账`, aligning the build description with acceptance criterion ④ and the landed #633 writer contract.
2. Added an owner comment fixing the disaster-gate seam: while #299's mutiny fact writer is absent, the mutiny boundary test may seed DB fact state directly; #299's corresponding wiring slice owns the later producer bridge. The same comment records that deformation-exposure substrate is partly landed in #622 and completed by #651, and forbids a parallel producer in #655.

Canonical evidence: <https://github.com/Akagilnc/ming-salvage-sim/issues/655#issuecomment-5385111552>
