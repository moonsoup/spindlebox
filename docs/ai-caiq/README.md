# AI-CAIQ — SPIndlebox

Self-assessment of SPIndlebox against CSA's **AI-CAIQ v1.1.0 / AICM v1.1.0**.

| File | What it is |
|---|---|
| [`spindlebox.yaml`](spindlebox.yaml) | The diffable source of record — answers plus the evidence for each |
| `AI-CAIQ-spindlebox-v1.1.0.xlsx` | The generated workbook, filled from that source |

**This is an audit trail, not a STAR filing.** The point is that the tool can evidence its
own posture when asked.

## Scope — read before interpreting any answer

SPIndlebox is a **locally-run developer CLI**, MIT licensed. Not a hosted service, not
multi-tenant, no customer data, no model training or inference. It reads source trees on
the operator's own machine and writes `.spi/index.json` beside them. Most AICM controls
assume a service; that scoping is material to nearly every answer.

## Status — 10 of 247 answered (4.0%)

```
A&A  1/6    AIS  2/15   CCC  3/9    LOG  3/16   STA  1/16
```

2 Yes, 8 No. **The other 237 are UNASSESSED and are EMPTY in the workbook — not "No".**
Nobody has examined them against this subject yet, and silence must never read as a
finding.

A low number here is the correct output, not a shortfall. Every answered control traces to
a command that was actually run, with its observed result and date. Controls without that
were left alone.

## Regenerate

The pipeline lives in `~/Software/Rockin-robin` (which has `openpyxl`/`pyyaml`;
spindlebox's own deps are tree-sitter only). **Do not write a second filler** —
`fill_ai_caiq.py` is tested (10 passing) and already enforces the rules that matter.

```bash
cd ~/Software/Rockin-robin
python3 -m pytest scripts/test_fill_ai_caiq.py -q
python3 scripts/fill_ai_caiq.py \
  --template docs/ai-caiq/reference/AI_CAIQv1.1.0.xlsx \
  --answers ~/Software/spindlebox/docs/ai-caiq/spindlebox.yaml \
  --out ~/Software/spindlebox/docs/ai-caiq/AI-CAIQ-spindlebox-v1.1.0.xlsx
python3 scripts/ai_caiq_coverage.py \
  --workbook ~/Software/spindlebox/docs/ai-caiq/AI-CAIQ-spindlebox-v1.1.0.xlsx
```

The reference template is CSA's published blank and is **never committed** (see
Rockin-robin's `.gitignore`). Re-copy it from your CSA downloads if missing.

## Rules these answers follow

Inherited from `Rockin-robin/docs/ai-caiq/README.md`, which is the canonical statement:

1. **Every answer carries evidence** — the command run, the file, or the test that pins it.
2. **"No" is a legitimate answer.** A questionnaire answered "Yes" throughout is a red flag.
   A genuine PARTIAL is "No", with `implementation` saying what does exist.
3. **Unassessed is not "No".** Controls nobody examined are omitted, and stay empty.
4. **Negative findings state their search path** — "not found, having checked X, Y, Z".
5. **Name the right control.** `fill_ai_caiq.py` hard-errors on an ID the workbook does not
   define, which is the backstop against invented IDs.

A sixth, specific to this subject: **no answer here borrows evidence from Rockin-Robin or
the SSM factory.** Separate subjects, deliberately never merged.

## The two answers worth reading first

- **AIS-13 (AI Sandboxing) — No.** `spindlebox call` and `pipeline run` execute code from
  the *indexed* project in the caller's interpreter with no isolation;
  `dispatch.py:48` does `spec.loader.exec_module(module)`, so import-time side effects run
  before the selected function is even invoked. Indexing itself is static and safe. Do not
  run those two commands against untrusted source outside a container.
- **A&A-02 (Independent Assessments) — No.** These answers were produced by the same
  operator that maintains the code, using the same tooling. That is self-assessment, and
  the questionnaire says so rather than implying otherwise.
