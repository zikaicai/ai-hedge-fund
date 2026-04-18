import argparse
import json
import os
import yfinance as yf

def update_price():
    # Load the existing JSON data
    with open("prices.json", "r") as f:
        tickers_data = json.load(f)

    # Get the tickers from the JSON keys
    tickers = list(tickers_data.keys())

    # Download latest closing prices
    data = yf.download(tickers, period="1d", interval="1d", progress=False, auto_adjust=True)

    # Check if 'Close' is present
    if "Close" in data.columns:
        latest_closes = data["Close"].iloc[-1].to_dict()
    else:
        latest_closes = data.iloc[-1].to_dict()

    # Update the original dictionary
    for ticker in tickers:
        if ticker in latest_closes and latest_closes[ticker] is not None:
            tickers_data[ticker] = round(latest_closes[ticker], 2)

    # Save the updated data back to the JSON file
    with open("prices.json", "w") as f:
        json.dump(tickers_data, f, indent=4)

    print("Tickers updated successfully:")

def truncate(value):
    if value is None:
        return None
    return float(f"{value:.2f}")

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def execute_trade(portfolio, prices, ticker, action, shares):
    shares = int(shares)
    price = truncate(prices[ticker])
    pos = portfolio['positions'][ticker]
    gains = portfolio['realized_gains'][ticker]

    if action == 'buy':
        # --- Closing short positions first ---
        if pos['short'] > 0:
            closing_shares = min(pos['short'], shares)
            gain = truncate((pos['short_cost_basis'] - price) * closing_shares)
            gains['short'] = truncate(gains['short'] + gain)

            # Deduct buy-back cost from cash
            buyback_cost = truncate(price * closing_shares)
            portfolio['cash'] = truncate(portfolio['cash'] - buyback_cost)

            # Release margin
            margin_released = truncate(pos['short_cost_basis'] * closing_shares * portfolio['margin_requirement'])
            pos['short'] -= closing_shares
            pos['short_margin_used'] = truncate(pos['short_margin_used'] - margin_released)
            portfolio['margin_used'] = truncate(portfolio['margin_used'] - margin_released)

            shares -= closing_shares

        # --- Buying long positions ---
        if shares > 0:
            total_cost = truncate(price * shares)
            new_total = pos['long'] + shares
            existing_long_cost = pos['long_cost_basis'] if pos['long_cost_basis'] is not None else 0.0
            pos['long_cost_basis'] = truncate(
                (pos['long'] * existing_long_cost + shares * price) / new_total
            )
            pos['long'] += shares
            portfolio['cash'] = truncate(portfolio['cash'] - total_cost)

    elif action == 'sell':
        # --- Closing long positions ---
        if pos['long'] > 0:
            closing_shares = min(pos['long'], shares)
            gain = truncate((price - pos['long_cost_basis']) * closing_shares)
            gains['long'] = truncate(gains['long'] + gain)
            pos['long'] -= closing_shares

            proceeds = truncate(price * closing_shares)
            portfolio['cash'] = truncate(portfolio['cash'] + proceeds)
            shares -= closing_shares

        # --- Selling short (opening short positions) ---
        if shares > 0:
            new_total = pos['short'] + shares
            existing_short_cost = pos['short_cost_basis'] if pos['short_cost_basis'] is not None else 0.0
            pos['short_cost_basis'] = truncate(
                (pos['short'] * existing_short_cost + shares * price) / new_total
            )
            pos['short'] += shares

            proceeds = truncate(price * shares)
            portfolio['cash'] = truncate(portfolio['cash'] + proceeds)

            margin_used = truncate(price * shares * portfolio['margin_requirement'])
            pos['short_margin_used'] = truncate((pos['short_margin_used'] or 0.0) + margin_used)
            portfolio['margin_used'] = truncate((portfolio['margin_used'] or 0.0) + margin_used)

    else:
        raise ValueError("Invalid action. Use 'buy' or 'sell'.")

    # Clear cost basis and margin when no holdings remain
    if pos['long'] == 0:
        pos['long_cost_basis'] = None
    if pos['short'] == 0:
        pos['short_cost_basis'] = None
        pos['short_margin_used'] = None

    # Final truncations
    portfolio['cash'] = truncate(portfolio['cash'])
    pos['long_cost_basis'] = truncate(pos['long_cost_basis'])
    pos['short_cost_basis'] = truncate(pos['short_cost_basis'])
    pos['short_margin_used'] = truncate(pos['short_margin_used'])

def calculate_equity(portfolio, prices):
    equity = portfolio['cash']
    for ticker, pos in portfolio['positions'].items():
        price = truncate(prices[ticker])
        long_value = pos['long'] * price
        short_value = pos['short'] * price
        equity += truncate(long_value - short_value)
    return truncate(equity)

def display_status(portfolio, prices, margin_requirement=0.5):
    equity = portfolio['cash']
    margin_used = 0.0

    print("==== Portfolio Status ====")
    print(f"Cash: ${portfolio['cash']:.2f}")

    print(f"{'Ticker':<8} {'Pos':<6} {'Shares':<8} {'Cost Basis':<12} {'Price':<10} {'Unrealized P/L':<18}")
    print("-" * 70)

    for ticker, pos in portfolio['positions'].items():
        price = truncate(prices[ticker])
        unrealized_long = 0.0
        unrealized_short = 0.0

        if pos['long'] > 0:
            unrealized_long = truncate((price - pos['long_cost_basis']) * pos['long'])
            equity += truncate(pos['long'] * price)

        if pos['short'] > 0:
            unrealized_short = truncate((pos['short_cost_basis'] - price) * pos['short'])
            equity -= truncate(pos['short'] * price)
            margin_used += truncate(price * pos['short'] * margin_requirement)
            pos['short_margin_used'] = truncate(price * pos['short'] * margin_requirement)

        unrealized_total = unrealized_long + unrealized_short

        position_type = "Long" if pos['long'] > 0 else "Short" if pos['short'] > 0 else "-"
        shares = pos['long'] if pos['long'] > 0 else pos['short']
        cost_basis = pos['long_cost_basis'] if pos['long'] > 0 else pos['short_cost_basis']

        if shares > 0:
            display_cost = f"${cost_basis:.2f}" if cost_basis is not None else "-"
            display_price = f"${price:.2f}" if price is not None else "-"
            display_unrealized = f"${unrealized_total:+.2f}"
            print(f"{ticker:<8} {position_type:<6} {shares:<8} {display_cost:<12} {display_price:<10} {display_unrealized:<18}")

    print("-" * 70)
    print(f"Margin Used: ${margin_used:.2f}")
    print(f"Total Equity: ${equity:.2f}")
    print("===============================")

    portfolio['margin_used'] = truncate(margin_used)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker')
    parser.add_argument('--action', choices=['buy', 'sell'])
    parser.add_argument('--shares', type=int)
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--portfolio', default='portfolio.json')
    parser.add_argument('--prices', default='prices.json')
    args = parser.parse_args()

    if args.update:
        update_price()

    prices = load_json(args.prices)
    portfolio = load_json(args.portfolio)

    if args.status:
        display_status(portfolio, prices)
        save_json(args.portfolio, portfolio)
        return

    if not (args.ticker and args.action and args.shares):
        raise ValueError("To trade, you must specify --ticker, --action, and --shares.")

    execute_trade(portfolio, prices, args.ticker, args.action, args.shares)
    save_json(args.portfolio, portfolio)

    total_equity = calculate_equity(portfolio, prices)
    print(f"Trade executed: {args.action} {args.shares} shares of {args.ticker}")
    print(f"Cash balance: ${portfolio['cash']:.2f}")
    print(f"Total equity: ${total_equity:.2f}")

if __name__ == '__main__':
    main()