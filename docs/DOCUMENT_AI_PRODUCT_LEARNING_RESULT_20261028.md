# Product matching learning experiment — 28 October 2026

The first bounded HQ training round completed, but the trained ranker is **held, not selected**. Validation ranking regressed and six new wrong identity proposals appeared across the development partitions. No production behavior, approved alias, receipt, or product master was changed.

The private frozen dataset contains 7,040 catalogue products and 1,302 source rows. Eligibility admits 616 receipt-corroborated saved LLM silver identity labels, seven user-confirmed identity-only labels and seven explicit catalogue-absence controls. Another 672 unconfirmed rows are quarantined. Whole-row human gold and glyph-training examples are both zero. Raw machine OCR, saved source-reading proposals and business corrections remain separate.

Source hashes, supplier-scoped invoice identifiers and receipt identifiers form connected groups before the fixed train/validation/test split. These are known development data; group separation does not establish accuracy on independently collected new invoices.

| Partition | Known identities | First-ranked correct, before → after | Correct review proposals, before → after | Wrong review proposals, before → after |
|---|---:|---:|---:|---:|
| Train | 437 | 309 → 308 | 90 → 116 | 6 → 9 |
| Validation | 82 | 51 → 49 | 21 → 23 | 0 → 1 |
| Test partition | 104 | 75 → 82 | 25 → 29 | 0 → 0 |

The partitions additionally contain four, one and two explicit catalogue-absence controls respectively. All seven abstained before and after. Their known-absence flag tests policy enforcement, not detection accuracy for an unseen new product.

| Paired change | Train | Validation | Test partition |
|---|---:|---:|---:|
| First-ranked identity fixed | 21 | 5 | 11 |
| Previously correct first-ranked identity lost | 22 | 7 | 4 |
| Additional correct review proposal | 26 | 2 | 4 |
| Previously correct review proposal lost | 0 | 0 | 0 |
| New wrong review proposal | 5 | 1 | 0 |
| Old wrong review proposal removed | 2 | 0 | 0 |

Training ran only on HQ: 437 examples, 3,496 distinct candidate pairs, 20 epochs and **69,920 actual updates**. It produced 273 periodic checkpoints and one final checkpoint. Training took 75.94 seconds, with peak owned-process-tree memory of 156,647,424 bytes; the supervisor reported all owned processes closed and the shared lock released.

V1 learns name similarity, explicit strength/form/pack specifications and exact identifier features. Supplier, chronology, invoice co-occurrence, unit conversion and quantity conversion are not model features. The actual dataset queries contain no exact company-code or barcode inputs, so this run does not measure real-data identifier safeguard coverage. Model-free tests cover identifier disagreement, nonunique barcodes and explicit specification conflicts.

The retained failure cases include brand/model substitution and one-item versus multi-item pack confusion. Missing specification evidence can still admit a nearby variant: absence of a detected conflict is not proof of matching strength, formula, form or pack. The learned pack-conflict coefficient became positive, although an independent hard gate still rejects explicitly detected conflicts. This is further reason to retain the experiment without adoption.

Private split/company comparisons, source-bound paired cases, original HQ results and checkpoint integrity evidence are stored outside Git in the experiment audit folder. The next change should address these identified variant and missing-evidence failures before another separately authorized, frozen-data experiment; this report does not request or start another training round.

## Casebook priorities for the next implementation

1. **Brand, variant and device model identity.** Preserve explicit brand/model tokens and reject contradictory model numbers. A shared product category such as a mesh nebulizer is insufficient evidence to substitute one manufacturer/model for another. Add counterexamples for adult versus kids variants and flavour/formula suffixes.
2. **Pack hierarchy and missing contents.** Represent item strength/size, contents per retail SKU and outer invoice pack separately. One tube, a two-tube retail SKU and an outer carton are different facts. When source contents are unknown and near candidates differ by contents, abstain rather than treating absence of conflict as agreement. Preserve ambiguous OCR characters instead of silently turning them into pack quantities.
3. **Feature constraints and explanation coverage.** Keep contradiction gates independent of learned scores, constrain or remove a learned reward for pack conflict, and report which critical identity fields remain unknown. Source-exact barcode/company-code evidence needs independent labelled examples before its learned weights can be evaluated.

Freeze these changes and their negative controls before comparing them with the retained baseline. The current report changes neither the manifest nor the trained model and starts no additional fitting.
