# Palomar specialty P&C peer data review

Palomar uses the dedicated `INSURER_US_P&C` methodology. The non-capital H1 2026 peer data are usable, but Fundamental Quality remains deliberately blocked because `capital_strength` is a required component.

## Capital-strength basis

The preferred capital metric is `net_written_premium_to_surplus_ratio`; `rbc_ratio_pct` remains a fallback alias when an exact, comparable RBC ratio is publicly available.

For premium-to-surplus, the reference basis is fixed **before** collection:

- numerator: FY2025 statutory net written premium;
- denominator: FY2025 year-end policyholders' surplus;
- accounting basis: U.S. statutory accounting;
- target and peers must use the same fiscal-year basis;
- H1/YTD premium is never annualized as a substitute;
- consolidated GAAP premium may not be mixed with legal-entity statutory surplus.

The existing H1 2026 underwriting, profitability and growth observations remain unchanged. The FY2025 statutory capital metric is a deliberately separate period class.

## Verified FY2025 observations

### Kinsale Insurance Company

- Statutory net premium: 1,613,698,222
- Capital & surplus: 1,929,905,376
- IRIS #2 net premium-to-surplus ratio: **83.6%**
- Source: FSLSO 2025 annual insurer financial report.

### RLI Corp. insurance subsidiaries

- Statutory net premiums written: 1,622,129,000
- Policyholders' surplus: 1,846,615,000
- Reported ratio: **0.88 to 1**, stored as **88.0%**
- Source: RLI 2025 Form 10-K.

## Observations deliberately not scored

- **Palomar / PSIC:** FY2025 statutory year-end surplus is publicly cross-checkable, but a homogeneous statutory FY2025 net-written-premium numerator has not yet been accepted into the dataset. A third-party 172.77% ratio is a useful cross-check, not an accepted score source.
- **Skyward:** Houston Specialty Insurance Company reported a 121% net-premium-to-surplus ratio at 2025-09-30. This is an interim legal-entity observation, not an FY2025 value on the locked basis.
- **Heritage:** the 2025 annual report says each insurance subsidiary maintained RBC above 300%, but does not disclose an exact ratio. A lower bound is not converted into a score.
- **HCI:** no homogeneous FY2025 statutory capital observation has been accepted in this pass.

## Readiness consequence

Two homogeneous FY2025 peer values are now stored, but production scoring still requires the target plus at least four eligible peers. `capital_strength` therefore remains missing and PLMR must remain `DATA_CHECK`.

No value is inferred from GAAP/statutory scope mixing and no missing value is treated as zero.
