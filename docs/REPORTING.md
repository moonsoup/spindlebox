# Reports — SPIndlestacks

A report is not code. It is a **stack**: a small data file naming an ordered
chain of ops, each one `ctx in → ctx out` — the same calling convention as
everything else in SPIndleframe. Collectors fill `title` / `columns` / `rows`;
one renderer turns them into `output` in the format you asked for. The chain is
type-checked before it runs.

## Use

```bash
spindlebox report                         # list every report and its status
spindlebox report typing-health           # run one (markdown to stdout)
spindlebox report typing-health --format csv        # spreadsheet
spindlebox report dup-candidates --format html --out dups.html   # print → PDF
spindlebox report compile-matrix --project myproj   # one project only
spindlebox report score-history --check             # validate, don't run
```

Formats: `md` (default) · `csv` · `html` · `json`. Every report accepts
`--project`, `--out`, and `--ctx '{...}'` for stack-specific overrides.

## The reports

| Report | Answers |
|---|---|
| `typing-health` | Where does code collapse to `any`? Which files hurt migration most? |
| `dup-candidates` | What has been written more than once, across every indexed repo? |
| `compile-matrix` | Which projects generate into which output languages? |
| `score-history` | Every hardening-harness run, scored and versioned. |

Reports read the SPI indexes of **registered projects** — run
`spindlebox index <path>` first; `--project` names one, otherwise all.

## Anatomy of a stack

`spindlebox/reporting_stacks/typing-health.stack.json`:

```json
{
  "report": "typing-health",
  "description": "Where untyped code hides",
  "stages": ["collect.typing_health", "render.table"],
  "ctx": {"project": null},
  "default_format": "md"
}
```

`stages` is the pipeline. Each op declares what ctx keys it `requires` and
`provides`; `spindlebox report <name> --check` verifies the chain is satisfied
end-to-end and terminates in `output` — a stack that would fail is refused
before it runs, the same compile-time stance as `spindlebox validate`.

## Add a report in three steps

1. **Reuse first.** If an existing collector computes what you need, your
   report is *only* a stack file. Drop `myreport.stack.json` next to the others.
2. Otherwise add one collector to `spindlebox/reporting.py`:

   ```python
   @report_op("collect.myreport", requires=set(), provides={"title", "columns", "rows"})
   def collect_myreport(ctx):
       ctx.update(title="…", columns=[…], rows=[…])
       return ctx
   ```

   Every format is already handled — collectors never touch presentation.
3. `spindlebox report myreport --check`, write a test, done.
