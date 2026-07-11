"""Track planner token spend against the loop's cost budget."""

# $ per million tokens (input, output). Keep in sync with the planner model in
# openai_planner.py. Prices are approximate — confirm against OpenAI's current
# pricing page; the OpenAI API may also return a dated model id (e.g.
# 'gpt-5.1-2025-...'), which falls back to DEFAULT_PRICING below.
PRICING_PER_MTOK = {
    'gpt-5.1': {'input': 1.25, 'output': 10.0},
}
DEFAULT_PRICING = {'input': 1.25, 'output': 10.0}


def compute_cost(usage):
    """usage: {'input_tokens': int, 'output_tokens': int, 'model': str}."""
    pricing = PRICING_PER_MTOK.get(usage.get('model'), DEFAULT_PRICING)
    input_cost = usage.get('input_tokens', 0) / 1_000_000 * pricing['input']
    output_cost = usage.get('output_tokens', 0) / 1_000_000 * pricing['output']
    return round(input_cost + output_cost, 6)
