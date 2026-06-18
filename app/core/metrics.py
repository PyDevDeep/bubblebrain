from prometheus_client import Counter, Histogram

# LLM Metrics
llm_requests_total = Counter(
    "llm_requests_total", "Total number of LLM requests made", ["model", "status"]
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total number of tokens used by LLM",
    ["model", "token_type"],  # prompt or completion
)

llm_latency_seconds = Histogram(
    "llm_latency_seconds", "Latency of LLM requests in seconds", ["model"]
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total", "Total estimated cost of LLM requests in USD", ["model"]
)

# Bot General Metrics
bot_messages_total = Counter(
    "bot_messages_total",
    "Total number of messages processed by the bot",
    ["status"],  # e.g. success, error
)

price_alerts_total = Counter(
    "price_alerts_total", "Total number of price mismatch alerts generated"
)

leads_created_total = Counter(
    "leads_created_total",
    "Total number of leads created",
    ["type", "status"],  # type: contact, checkout (hot lead), conversion
)
