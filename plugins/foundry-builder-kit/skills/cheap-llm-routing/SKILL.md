---
name: cheap-llm-routing
description: Route a narrow, schema-pinned LLM task (extraction, classification, scoring, short structured grading) to a free or cheap model instead of a frontier model, without leaking user data and without making the feature depend on a free tier. Covers the privacy bar (check the provider's data policy before its rate limit), the forced tool-call pattern, schema validation, key-format gating, and the paid fallback. Use when the user says "make this feature free", "this API bill is too high", "use a cheaper model for this", "use Groq / Gemini / OpenRouter / Ollama", "don't burn API credits on this", or before sending user-submitted data to any free-tier model.
---

# cheap-llm-routing: free structured output that does not leak or break

## When this applies, and when it does not

Applies: one call, one small JSON Schema, a bounded answer. Examples: "classify this ticket into 5 categories", "pull name, school, and graduation year from this resume", "score this answer 1 to 5 against the rubric".

Does not apply: long-form writing, multi-step reasoning, code generation, anything where a wrong answer is expensive. Use your normal model there. Cheap models fail quietly on hard tasks; the schema only constrains the format, not whether the answer is right.

## Rule 1: the privacy bar comes before the rate limit

The first question about a provider is not "how many requests per minute" but **"does this tier use my inputs for training or product improvement?"** If the input is real user data (anything a person typed expecting it to stay with you: a resume, a support message, a grade, a chat), a provider that trains on it is disqualified, however generous its limits.

Classify every call:

- `private`: real user data. Only providers whose terms, for the tier you are on, rule out training on your inputs.
- `public`: synthetic data, public web pages, your own docs.

How to check a provider (do it yourself, write down the date):

1. Find the provider's data processing addendum (DPA) or API terms, not a blog post or a model card.
2. Look for: training on inputs, retention period, human review, and whether the free tier has different terms from paid.
3. Record it next to the provider config: `"policy_checked": "2026-01-15: <link>"`.

Starting point from our own review (Aug 2026, re-check before you rely on it; policies change):

| Provider | Free tier | Private data? | Notes |
|---|---|---|---|
| Groq | Developer tier | Yes, per its DPA at the time | Same DPA on free and paid; OpenAI-compatible API; key prefix `gsk_` |
| Google Gemini API | Free tier | No | Free-tier terms allow using inputs to improve products; the paid tier differs |
| OpenRouter `:free` models | Free | No by default | Policy depends on the downstream provider; check the privacy settings page |
| Ollama (local) | Your hardware | Yes | Nothing leaves the machine; quality depends on the model size you can run |
| Anthropic / OpenAI paid API | Paid | Yes | Commercial API terms do not train on inputs by default; the paid fallback |

## Rule 2: forced tool call, never "reply in JSON"

Every provider above supports function calling. Force the model to call your one tool:

- OpenAI-compatible (Groq, Gemini, OpenRouter, Ollama): `tools=[{"type":"function","function":{"name":..., "parameters": schema}}]` and `tool_choice={"type":"function","function":{"name":...}}`. The result arrives in `choices[0].message.tool_calls[0].function.arguments` as a **JSON string**. Parse it inside a try block.
- Anthropic: `tools=[{"name":..., "input_schema": schema}]`, `tool_choice={"type":"tool","name":...}`. The result is `content[i].input`, already an object.

Write the schema tight: `enum` for categories, `minimum`/`maximum` for scores, `maxLength` on strings, `maxItems` on arrays, `additionalProperties: false`. Example: `${CLAUDE_SKILL_DIR}/examples/ticket-schema.json`.

## Rule 3: validate, then fall through

A 200 response with an off-schema payload is a failure. Validate the parsed result against the schema; if it fails, try the next provider.

## Rule 4: never the only path

Free tiers have no uptime promise and change limits without notice. Order the chain cheapest first and end with a paid provider you trust. An outage then costs a few cents, not a broken feature. Log which provider answered, so you can see the free share and notice when it drops to zero.

## Rule 5: "configured" means a valid-looking key

A variable set to `YOUR_KEY_HERE` is non-empty and useless. Gate on the provider's real key prefix (Groq `gsk_`, Anthropic API keys `sk-ant-api`, OpenRouter `sk-or-`, Gemini `AIza`) so a placeholder skips cleanly instead of sending a doomed request on every call.

## The bundled router (Python stdlib)

`${CLAUDE_SKILL_DIR}/scripts/structured_router.py` implements all five rules. Copy it into your project (it is one file, no dependencies) or call it from the CLI.

See the route before spending anything:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/structured_router.py" \
  --schema "${CLAUDE_SKILL_DIR}/examples/ticket-schema.json" \
  --data-class private --plan
```

Example output:

```
SKIP ollama-local     qwen2.5:7b-instruct  (opt-in env ROUTER_USE_OLLAMA=1 not set)
TRY  groq             llama-3.3-70b-versatile  (key ok)
SKIP gemini-free      gemini-2.5-flash  (fails privacy bar for private data)
SKIP openrouter-free  meta-llama/llama-3.3-70b-instruct:free  (fails privacy bar for private data)
TRY  anthropic        claude-haiku-4-5  (key ok)
```

Run it on synthetic input:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/structured_router.py" \
  --schema "${CLAUDE_SKILL_DIR}/examples/ticket-schema.json" \
  --system "Classify this support ticket." \
  --input "${CLAUDE_SKILL_DIR}/examples/ticket.txt" \
  --data-class private
```

In Python:

```python
from structured_router import call_structured, RouterError

try:
    data, provider = call_structured(
        system="Classify this support ticket.",
        user=ticket_text,
        tool_name="emit_ticket",
        schema=TICKET_SCHEMA,
        data_class="private",
    )
except RouterError as exc:
    # every provider failed: show a friendly error, log exc.attempts
    raise
```

Provider list: edit `DEFAULT_PROVIDERS`, or pass a JSON file (`--providers` or env `STRUCTURED_ROUTER_PROVIDERS`); example in `${CLAUDE_SKILL_DIR}/examples/providers.json`. Model names change; check each provider's model list. Override the defaults with `ROUTER_GROQ_MODEL`, `ROUTER_GEMINI_MODEL`, `ROUTER_OPENROUTER_MODEL`, `ROUTER_ANTHROPIC_MODEL`, `ROUTER_OLLAMA_MODEL`.

### TypeScript / Next.js shape

Same pattern in two files: `lib/llm/groq.ts` (raw OpenAI-compatible call, `JSON.parse` on `arguments` in a try/catch, throws on any failure) and `lib/llm/structured.ts` (try the cheap provider, catch, call the paid one, validate both with `zod`). Call sites import only `structured.ts`, so switching providers is a one-file change.

## Gotchas

- **Two places for the key on a hosted app.** Set it in `.env.local` for dev AND in the host's env settings, then redeploy. Without the redeploy the live app keeps using the fallback forever, and nothing errors.
- **A stale exported variable shadows a fixed `.env`.** If the router says a key is a placeholder right after you fixed it, print the prefix from the same process: `python3 -c "import os; print(os.environ.get('GROQ_API_KEY','')[:4])"`.
- **Record the free path as $0 in cost logs, with a comment.** If the account later moves to pay-as-you-go, update it.
- **Do not test with real user data.** Use synthetic input until the privacy check is written down.

## Verify (before calling the integration done)

1. The key authenticates: `curl -sS -o /dev/null -w '%{http_code}\n' https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"` prints `200`.
2. `--plan` shows the route you expect for `--data-class private` (no provider with `private_ok: false`).
3. One real call on synthetic input returns schema-valid JSON, and stderr names the provider.
4. Fallback works: run once with the cheap key set to `gsk_invalid`; the answer must come from the paid provider.
5. Spot-check 10 outputs by hand against what a person would answer. Format passing is not quality passing.
