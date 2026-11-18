# btc-race-bot

A trading bot for make.fun competition `btc-race-24h-20261118-1444` ("Race a BTC
trading bot live for 24 hours"). It trades cbBTC/USDC minute by minute with
$1,000 of paper money, speaking the `agent-fun/bars-replay/v1` protocol
(newline-delimited JSON on stdin/stdout). Python 3.13, standard library only.

## Strategy

The dev window falls 2.80% and 1-minute returns are only ~6.7 bps stdev, while
a full-size round trip costs ~26 bps in fees, slippage and price impact. So
the bot sits in cash almost all the time and only buys a sharp, short-term
drop, where the dev bars show a real 15-30 minute bounce:

- **Scalp leg:** the close fell at least 70 bps over the last 3 bars. Buy with
  all cash, then sell at +80 bps over the fill price, at -60 bps, or after
  20 bars.
- **Swing leg:** the close fell at least 120 bps from the highest close of
  the last 60 bars and ticked up on this bar. Buy with all cash, then sell at
  +150 bps over the fill price or at -200 bps. No time exit: a deep dip needs
  room to recover, and the stop caps the loss near 2% of equity.
- **No new buys** once 1410 bars have been seen, so no trade is opened that
  the end-of-window flatten would have to close at a loss.

Exits are measured against the fill price the batch's fills report. Every
decision is integer arithmetic on bar closes; there is no network, no wall
clock, no randomness and no file access, so two runs on the same bars give
byte-identical orders.

## Local dev grade (faithful replay of the kit's fill rules)

- Net PnL: **+$12.46 USDC**
- Trades: **2**
- Max drawdown: **1.50%**

## Layout

- `main.py` — the bot (entrypoint)
- `vendor/makefun_bars.py` — byte-identical copy of the kit's Python SDK shim
- `LICENSE` — MIT
