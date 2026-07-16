# Windows smoke checklist (AT-GOV-011)

| Field | Value |
|---|---|
| Requirement | `GOV-011` / `AT-GOV-011` |
| Status | `not_run` |
| Reason | Desktop smoke hosts not confirmed available for matrix execution |

## Matrix

| Host | OS | Cursor | Node.js | PowerShell | Status |
|---|---|---|---|---|---|
| Desktop A | Windows 10 x64 | 3.11.25 | 22.x | 5.1 | `not_run` |
| Desktop B | Windows 11 x64 | 3.11.25 | 22.x | 5.1 | `not_run` |
| Capability spike (reference only) | Windows 10 | 3.11.25 | 22.22.2 | 5.1.19041.6456 | observed for capability baseline, **not** Desktop parity evidence |

## Commands to run when hosts are available

```powershell
node tools/quality/run-quality-suite.mjs
node tools/quality/ci-recompute.mjs
```

Both Desktop hosts must return the same governance verdict for identical trusted inputs. A hosted CI run (when eventually approved) must not be presented as Desktop compatibility evidence.
