# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Hedge Fund — an LLM-powered multi-agent trading system for educational/research purposes. Multiple specialized AI analyst agents (modeled after famous investors) generate trading signals, which are aggregated by a risk manager and portfolio manager to produce final trading decisions. Not for real trading.

## Commands

```bash
# Install dependencies
poetry install

# Run hedge fund (single analysis)
poetry run python src/main.py --tickers AAPL,MSFT,NVDA
poetry run python src/main.py --tickers AAPL --start-date 2024-01-01 --end-date 2024-03-01
poetry run python src/main.py --tickers AAPL --ollama  # local LLMs

# Run backtester
poetry run python src/backtester.py --tickers AAPL,MSFT

# Run tests
pytest tests/
pytest tests/backtesting/test_portfolio.py           # single test file
pytest tests/backtesting/integration/                # integration tests

# Formatting & linting
black src/ tests/       # formatter (420 char line length, configured in pyproject.toml)
isort src/ tests/       # import sorting (black profile)
flake8 src/ tests/      # linter

# Web app
./run.sh                # starts both backend and frontend
```

## Architecture

### Agent Pipeline (LangGraph StateGraph)

```
CLI args → create_workflow() → LangGraph StateGraph
                                    │
                          Selected Analyst Agents (parallel)
                                    │
                            Risk Manager Agent
                                    │
                          Portfolio Manager Agent
                                    │
                              Final Decisions
```

All agents share state via `AgentState` (TypedDict in `src/graph/state.py`) containing `messages`, `data` (tickers, portfolio, signals), and `metadata` (model config).

### Key Modules

- **`src/agents/`** — 18+ analyst agents (warren_buffett, cathie_wood, technicals, sentiment, etc.) plus risk_manager and portfolio_manager. Each fetches data, calls an LLM with a Pydantic model for structured output, and returns a signal (bullish/bearish/neutral + confidence + reasoning).
- **`src/tools/api.py`** — Financial data fetching (yfinance for prices, FinancialDatasets API for metrics/filings/insider trades).
- **`src/data/cache.py`** — JSON-based in-memory cache with file persistence for API data.
- **`src/llm/models.py`** — LLM provider abstraction supporting OpenAI, Anthropic, Groq, DeepSeek, Google, xAI, Azure OpenAI, GigaChat, Ollama. Model definitions in `api_models.json` and `ollama_models.json`.
- **`src/utils/llm.py`** — `call_llm()` wrapper with retry logic (3 attempts), structured Pydantic output, thread-safe lock. Handles JSON vs non-JSON mode providers.
- **`src/cli/input.py`** — CLI argument parsing, interactive model selection via questionary.
- **`src/backtesting/`** — Backtesting engine: daily loop running agents, executing trades, tracking portfolio (long/short positions, margin), computing metrics (Sharpe, Sortino, max drawdown).
- **`app/backend/`** — FastAPI REST API with SQLAlchemy ORM.
- **`app/frontend/`** — React + Vite + TypeScript + Tailwind CSS.

### Agent Pattern

Every analyst agent follows the same structure:
```python
def agent_name(state: AgentState, agent_id: str = "agent_name_agent") -> dict:
    data = state["data"]
    for ticker in data["tickers"]:
        # Fetch data via src/tools/api.py
        # Build analysis prompt
        # result = call_llm(prompt, SignalPydanticModel, agent_name=agent_id, state=state)
        # Collect signal
    return {"messages": [HumanMessage(content=json.dumps(...))], "data": {...}}
```

### Extending

| Task | Where |
|------|-------|
| Add new analyst agent | Create `src/agents/new_agent.py`, register in `src/utils/analysts.py` |
| Add LLM provider | Update `src/llm/models.py` and `api_models.json` |
| Modify CLI options | `src/cli/input.py` |

## Environment

Requires Python 3.11+. API keys configured via `.env` file (see `.env.example`). Free financial data is limited to AAPL, GOOGL, MSFT, NVDA, TSLA without a FinancialDatasets API key.
