# Separate engineering observations

Recorded during the 2026-11-13 export/session repair. **Deferred; not implemented as part of that repair.** These require their own semantic-inference, recommendation and presentation regressions.

1. **Phone-number semantics:** phone numbers should not be treated as numerical measurements. The synthetic quality fixture currently illustrates this risk: numerical inference can remove a leading plus sign. Export tests preserve the active snapshot; they do not claim to reverse ingestion inference.
2. **Identifier recommendations:** record IDs and similar identifiers should not receive inappropriate numeric-conversion recommendations. Preserve formatting and leading zeros.
3. **Date-specific checks:** date-like columns should receive suitable date-format/validity checks instead of irrelevant spelling checks. Ambiguous date formats still require explicit user decisions.
4. **Numeric presentation:** avoid floating-point display artifacts without silently rounding or modifying stored/exported data. Keep presentation policy separate from data precision.

No changes to ingestion, profiling, recommendations, cleaning or numeric formatting were made for these observations.
