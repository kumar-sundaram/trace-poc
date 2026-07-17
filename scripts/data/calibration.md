# PNI demo calibration

auto_match 0.92 (cosine 0.84) · no_match 0.75 (cosine 0.50) · T4 MATCH ratio >= 0.78

- **T1 — exact identifier** — expect `T1`, actual `T1 exact_identifier`, top score 1.000 vs `ALPHA 100 LLC`
- **T2 — normalized name + address** — expect `T2`, actual `T2 normalized_name_address`, top score 1.000 vs `PATRICIA MORRISON`
- **T3 — vector auto-match** — expect `T3`, actual `T3 vector (0.973)`, top score 0.973 vs `PATRICIA MORRISON`
- **T4 — AI disambiguation** — expect `T4`, actual `T4 MATCH (ratio 0.828)`, top score 0.896 vs `PATRICIA MORRISON`
- **REFUSAL — numeric guard** — expect `NEW PARTY`, actual `T4 NO_MATCH (numeric name tokens differ; distinct registrations) -> NEW PARTY`, top score 0.988 vs `ALPHA 100 LLC`
- **REFUSAL — last-name guard** — expect `NEW PARTY`, actual `T4 NO_MATCH (last names differ) -> NEW PARTY`, top score 0.915 vs `PATRICIA MORRISON`
