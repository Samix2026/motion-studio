# COST_GATE.md — pre-generation cost approval (Video Studio Agent)

The cost gate estimates the cost of planned **paid** calls from an explicit
pricing catalog, presents it for human approval, and **blocks generation** until
approved. It never contacts a provider, never invents pricing, and never
modifies a video project.

It is a **separate** human gate from creative/technical review:

```
Plan → Cost Gate → Cost Approval → Generate → Compose → Preview
     → AI Review → Proposal Approval → Apply → Final
```

## Where it sits

- **After**: script/storyboard, scene count, asset plan, provider/model choice.
- **Before**: paid video generation, paid image generation, paid TTS, paid SFX,
  paid music, paid external API generation.
- **Independent of**: `review/` (which runs after the preview render). Do not
  merge the two gates.

## Layout

```
costgate/
  __init__.py
  schema.py          # plan + gate validation, whitelists
  gate.py            # estimation, decision, actuals, report (pure functions)
  cli.py             # build | show | approve | reject | actuals | status | check
  pricing.json       # the explicit pricing catalog (starts empty)
  state/             # <gate_id>.json
  reports/           # <gate_id>.md
  tests/
```

stdlib Python only, matching `review/`.

## Plan input

An asset plan lists the planned paid calls:

```json
{
  "project": "example-project",
  "items": [
    { "scene": 1, "asset_type": "video", "provider": "MiniMax", "model": "video-01",
      "requests": 1, "unit_basis": "request", "pricing_ref": "MiniMax.video-01.request" },
    { "scene": 3, "asset_type": "tts", "provider": "ElevenLabs",
      "model": "eleven_multilingual_v2", "quantity": 420, "unit_basis": "character" }
  ]
}
```

`asset_type` ∈ {video, image, tts, sfx, music, external_api}; `unit_basis` ∈
{request, character, second, minute, image, 1k_tokens}. `quantity` defaults to
`requests` for per-request pricing.

## Pricing catalog

`pricing.json` (or a file passed with `--pricing`) holds the only prices the
gate will use:

```json
{
  "currency": "USD",
  "checked_at": "2026-01-01T00:00:00Z",
  "sources": ["https://provider.example/pricing"],
  "prices": {
    "MiniMax.video-01.request": {
      "unit_price": 0.5, "confidence": "verified",
      "source": "https://provider.example/pricing", "checked_at": "2026-01-01"
    }
  }
}
```

Lookup key: `pricing_ref` if present, else `<provider>.<model>.<unit_basis>`.

- `unit_price: null` or `confidence: "unknown"` ⇒ **UNKNOWN**. The gate will not
  invent a price.
- `confidence: "verified"` ⇒ cost labeled `known`; `"estimated"` ⇒ `estimated`.
- The shipped catalog is empty on purpose: populate it from the provider's own
  published price page and record `source` + `checked_at`.

## Decisions and blocking

```bash
python3 costgate/cli.py build   <project> --plan <plan.json> [--pricing <p.json>] [--at ISO]
python3 costgate/cli.py show    <project>
python3 costgate/cli.py approve <project> --limit <usd> [--at ISO]
python3 costgate/cli.py reject  <project> [--at ISO]
python3 costgate/cli.py actuals <project> [--provider-billed <usd>] [--session-reported <usd>]
python3 costgate/cli.py status  <project>
python3 costgate/cli.py check   <project>     # exit 2 while blocked
```

Statuses: `awaiting_approval` → `approved` | `rejected` | `budget_exceeded`.

- Paid generation is allowed only when `status == "approved"`.
- If `estimated_total_usd > approved_cost_limit_usd` → **STOP**
  (`budget_exceeded`); nothing runs.
- Partial/unknown pricing never produces a fabricated total; it is surfaced as
  `UNKNOWN` (with the known subtotal and the unknown item count), and an
  approval with unknown items carries an explicit warning.
- No automatic budget approval in V1.

## Fields recorded in the run

`estimated_cost_usd`, `approved_cost_limit_usd`, `provider_billed_cost_usd`,
`session_reported_cost_usd`, `cost_variance_usd`, `pricing_checked_at`, plus the
existing `pricing_source` and `cost_status` (`RUN_METRICS.md`).

- `cost_variance_usd = provider_billed_cost_usd − estimated_cost_usd`, only when
  both are known.
- Never write an unmeasured number.

## Guarantees

- No provider/network calls anywhere in `costgate/` (enforced by a test).
- `build`, `set_decision`, and `record_actuals` are pure; only `save_gate` writes,
  and only under `costgate/state/` and `costgate/reports/`.
- No video project is read or written by the gate.

## Tests

```bash
python3 -m unittest discover -s costgate/tests -v
```

Covers: calculation from verified pricing; UNKNOWN pricing stays UNKNOWN; paid
call blocked before approval; budget exceed blocks generation; approval within
budget; reject blocks; unknown-approval flagged; variance; input immutability;
state round-trip; no network libraries; build writes nothing.
