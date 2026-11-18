"""Sharp-drop bounce bot for cbBTC/USDC, agent-fun/bars-replay/v1.

Strategy (long only, one position, full cash per trade, all integer math):

The dev window falls 2.80% with 1-minute returns of only ~6.7 bps stdev, while a
full-size round trip costs ~26 bps in fees, slippage and price impact. So the
bot sits in cash almost all the time and only buys a sharp, short-term drop,
where the event study on the dev bars shows a real 15-30 minute bounce:

* Scalp leg: the close fell at least 70 bps over the last 3 bars. Buy, then
  sell at +80 bps over cost, at -60 bps, or after 20 bars, whichever comes
  first.
* Swing leg: the close fell at least 120 bps from the highest close of the
  last 60 bars and ticked up on this bar (the fall is pausing). Buy, then sell
  at +150 bps over cost or at -200 bps. No time exit: a deep dip needs room
  to recover, and the stop caps the loss near 2% of equity.
* No new buys once 1410 bars have been seen, so no trade is opened that the
  end-of-window flatten would have to close at a loss.

Exits are measured against the fill price the batch's fills report, so the
bot never has to guess what it paid. Every decision is integer arithmetic on the bar closes
the hello / batch messages carry; there is no network, no wall clock, no
randomness and no file access, so two runs on the same bars give byte-identical
orders. The task terms: each hello opens the run, each batch carries one bar,
the bot answers with its orders, and the bar closes drive every decision.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# Scalp leg: 3-bar drop, in bps.
SCALP_BARS = 3
SCALP_DROP_BPS = 70
SCALP_TAKE_BPS = 80
SCALP_STOP_BPS = 60
SCALP_HOLD_BARS = 20
# Swing leg: drawdown from the 60-bar high, in bps, with an uptick.
SWING_BARS = 60
SWING_DROP_BPS = 120
SWING_TAKE_BPS = 150
SWING_STOP_BPS = 200
# Stop opening trades this many bars into the window.
NO_BUY_AFTER_BARS = 1410
# Max slippage versus the latest close, in bps, on every order.
MAX_SLIPPAGE_BPS = 100

# Closes seen so far, oldest first, as ints at the symbol's price scale.
closes = []
# Mode of the open position ("scalp" / "swing"), the batch seq whose bar its
# buy filled at, and the fill price of that buy; None / 0 while flat. Gains
# are measured against the fill price, the price the position was actually
# bought at, so a take-profit of 150 bps means the close is 150 bps above
# the price paid (the harness's cost, fees included, sits a few bps lower).
mode = None
entry_seq = None
entry_price = 0
# Client id of a buy sent but not yet reported filled or rejected.
pending_buy_id = None
pending_buy_mode = None


def _drop_bps(high, low):
    """(high - low) in bps of high, integer arithmetic, high > 0."""
    return (high - low) * 10000 // high


def _gain_bps(close):
    """The open position's gain over its fill price, in bps, or None."""
    if entry_price <= 0:
        return None
    return (close - entry_price) * 10000 // entry_price


def on_batch(state, batch):
    global mode, entry_seq, entry_price, pending_buy_id, pending_buy_mode

    # Fold this batch's fills in first: a filled buy opens the position in
    # its mode, a rejected buy or a filled sell closes it.
    for fill in batch.get("fills", []):
        if fill.get("symbol") != SYMBOL:
            continue
        if fill.get("client_id") == pending_buy_id:
            if fill.get("status") == "filled":
                mode = pending_buy_mode
                entry_seq = int(fill["fill_bar"])
                entry_price = int(fill["price"])
            pending_buy_id = None
            pending_buy_mode = None
        elif fill.get("side") == "sell" and fill.get("status") == "filled":
            mode = None
            entry_seq = None
            entry_price = 0

    fresh = False
    for bar in batch.get("bars", []):
        if bar.get("symbol") == SYMBOL:
            closes.append(int(bar["c"]))
            fresh = True
    if not fresh or state.warming_up:
        return []

    n = len(closes)
    close = closes[-1]
    held = state.positions.get(SYMBOL)

    if held is not None:
        gain = _gain_bps(close)
        if gain is None:
            return []
        bars_held = state.seq - entry_seq if entry_seq is not None else 0
        if mode == "scalp":
            if (
                gain >= SCALP_TAKE_BPS
                or gain <= -SCALP_STOP_BPS
                or bars_held >= SCALP_HOLD_BARS
            ):
                return [
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": held.qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                ]
        else:
            if gain >= SWING_TAKE_BPS or gain <= -SWING_STOP_BPS:
                return [
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": held.qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                ]
        return []

    # Flat: look for an entry. Never open a trade late in the window.
    if n >= NO_BUY_AFTER_BARS:
        return []
    buy_mode = None
    if n > SCALP_BARS:
        if _drop_bps(closes[-1 - SCALP_BARS], close) >= SCALP_DROP_BPS:
            buy_mode = "scalp"
    if buy_mode is None and n > SWING_BARS:
        high = max(closes[-SWING_BARS - 1:])
        if (
            _drop_bps(high, close) >= SWING_DROP_BPS
            and n >= 2
            and close > closes[-2]
        ):
            buy_mode = "swing"
    if buy_mode is None:
        return []

    cash = state.cash
    room = state.weight_room(SYMBOL)
    amount = cash if cash < room else room
    if amount < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    client_id = state.client_id()
    pending_buy_id = client_id
    pending_buy_mode = buy_mode
    return [
        {
            "side": "buy",
            "symbol": SYMBOL,
            "client_id": client_id,
            "notional_quote_units": amount,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }
    ]


makefun_bars.run(on_batch)
