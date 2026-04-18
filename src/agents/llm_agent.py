from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import (
    get_financial_metrics,
    get_market_cap,
    get_insider_trades,
    get_company_news,
    get_prices,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import json
from typing_extensions import Literal
from src.utils.progress import progress
from src.utils.llm import call_llm
from src.utils.api_key import get_api_key_from_state


class LLMSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str


def llm_agent(state: AgentState, agent_id: str = "llm_agent"):
    """
    Collects all available input data for tickers and forwards it to a general LLM
    for a next-day (T+1) trading decision. The LLM is instructed to return the
    same JSON structure as other analysts: signal, confidence, reasoning.
    """
    data = state["data"]
    start_date = data["start_date"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")

    results = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching financial metrics")
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5, api_key=api_key)

        progress.update_status(agent_id, ticker, "Getting market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching insider trades")
        insider_trades = get_insider_trades(ticker, end_date, limit=50, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching company news")
        company_news = get_company_news(ticker, limit=10, api_key=api_key)

        progress.update_status(agent_id, ticker, "Fetching recent price data")
        prices = get_prices(ticker, start_date=start_date, end_date=end_date, api_key=api_key)

        # Build prompt
        template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are an LLM assisting with next-day (T+1) trading decisions."
                    " Provide a concise trading recommendation (bullish/bearish/neutral) for the next trading day."
                    " Output must be valid JSON with keys: signal (bullish/bearish/neutral), confidence (0-100 float), and reasoning (string)."
                    " Use the provided analysis data below to form a T+1 view."
                """,
                ),
                (
                    "human",
                    """Analysis Data for {ticker}:
{analysis_data}

Return JSON exactly in this format:
{{
  "signal": "bullish|bearish|neutral",
  "confidence": float,
  "reasoning": "string"
}}
""",
                ),
            ]
        )

        analysis_payload = {
            "financial_metrics": [m.dict() for m in metrics] if metrics else [],
            "market_cap": market_cap,
            "insider_trades": [t.dict() for t in insider_trades] if insider_trades else [],
            "company_news": [n.dict() for n in company_news] if company_news else [],
            "prices": [p.dict() for p in prices] if prices else [],
        }

        prompt = template.invoke({"ticker": ticker, "analysis_data": json.dumps(analysis_payload, default=str, indent=2)})

        def default_signal():
            return LLMSignal(signal="neutral", confidence=0.0, reasoning="LLM failed to return a valid signal")

        llm_output = call_llm(
            prompt=prompt,
            pydantic_model=LLMSignal,
            agent_name=agent_id,
            state=state,
            default_factory=default_signal,
        )

        results[ticker] = {
            "signal": llm_output.signal,
            "confidence": llm_output.confidence,
            "reasoning": llm_output.reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=llm_output.reasoning)

    state["data"]["analyst_signals"][agent_id] = results

    if state["metadata"].get("show_reasoning"):
        show_agent_reasoning(results, "LLM Agent")

    message = HumanMessage(content=json.dumps(results), name=agent_id)
    progress.update_status(agent_id, None, "Done")

    return {"messages": [message], "data": state["data"]}
