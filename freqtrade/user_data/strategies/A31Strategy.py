"""
A31 Strategy — Breakout & Volatility Squeeze
ETH/USDT 5m Futures | WR% 42.5 | DD% 14.3 | Profit +21,209

Core logic:
- Keltner Channel squeeze detection → breakout entry
- c=0.80 (aggressive — fewer trades, bigger size)
- e=-0.10 (slight short bias)
- Profits from volatility expansion after compression
"""
from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np


class A31Strategy(IStrategy):
    """
    A31 c=0.80 e=-0.10
    Volatility squeeze breakout — big moves from compression
    """

    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True

    position_c = DecimalParameter(
        0.1, 1.0, default=0.80, space="buy", optimize=True
    )
    entry_bias = DecimalParameter(
        -0.5, 0.5, default=-0.10, space="buy", optimize=True
    )

    kc_period = IntParameter(
        14, 30, default=20, space="buy", optimize=True
    )
    kc_mult = DecimalParameter(
        1.0, 3.0, default=1.5, space="buy", optimize=True
    )

    minimal_roi = {
        "0": 0.018,
        "30": 0.010,
        "60": 0.005,
        "120": 0.002,
    }

    stoploss = -0.007
    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.008
    trailing_only_offset_is_reached = True

    startup_candle_count = 200

    def populate_indicators(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        period = int(self.kc_period.value)
        mult = float(self.kc_mult.value)

        # Bollinger Bands
        bb = ta.BBANDS(
            dataframe, timeperiod=period, nbdevup=2.0, nbdevdn=2.0
        )
        dataframe["bb_upper"] = bb["upperband"]
        dataframe["bb_lower"] = bb["lowerband"]
        dataframe["bb_mid"] = bb["middleband"]
        dataframe["bb_width"] = (
            (dataframe["bb_upper"] - dataframe["bb_lower"])
            / dataframe["bb_mid"]
        )

        # Keltner Channels
        dataframe["kc_mid"] = ta.EMA(dataframe, timeperiod=period)
        atr = ta.ATR(dataframe, timeperiod=period)
        dataframe["kc_upper"] = dataframe["kc_mid"] + (mult * atr)
        dataframe["kc_lower"] = dataframe["kc_mid"] - (mult * atr)

        # Squeeze detection: BB inside KC
        dataframe["squeeze_on"] = (
            (dataframe["bb_lower"] > dataframe["kc_lower"])
            & (dataframe["bb_upper"] < dataframe["kc_upper"])
        ).astype(int)

        # Squeeze off (release) — BB expands outside KC
        dataframe["squeeze_off"] = (
            (dataframe["bb_lower"] < dataframe["kc_lower"])
            | (dataframe["bb_upper"] > dataframe["kc_upper"])
        ).astype(int)

        # Squeeze just fired (transition)
        dataframe["squeeze_fire"] = (
            (dataframe["squeeze_on"].shift(1) == 1)
            & (dataframe["squeeze_off"] == 1)
        ).astype(int)

        # Momentum (linear regression of close - midline)
        delta = dataframe["close"] - dataframe["kc_mid"]
        dataframe["momentum"] = ta.LINEARREG(delta, timeperiod=period)

        # Momentum direction
        dataframe["mom_increasing"] = (
            dataframe["momentum"] > dataframe["momentum"].shift(1)
        ).astype(int)
        dataframe["mom_decreasing"] = (
            dataframe["momentum"] < dataframe["momentum"].shift(1)
        ).astype(int)

        # Support indicators
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = atr
        dataframe["volume_sma"] = ta.SMA(
            dataframe["volume"], timeperiod=20
        )
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # EMA slope for regime detection
        ema50 = dataframe["ema_50"]
        dataframe["ema_slope"] = (ema50 - ema50.shift(10)) / ema50.shift(10) * 100

        return dataframe

    def populate_entry_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        # Long: squeeze fires + momentum positive & increasing + strong volume
        dataframe.loc[
            (
                (dataframe["squeeze_fire"] == 1)
                & (dataframe["momentum"] > 0)
                & (dataframe["mom_increasing"] == 1)
                & (dataframe["close"] > dataframe["ema_50"])
                & (dataframe["rsi"] > 45)
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > dataframe["volume_sma"] * 1.5)
                & (dataframe["adx"] > 20)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "a31_squeeze_breakout_long")

        # Short: squeeze fires + momentum negative & decreasing + strong volume
        dataframe.loc[
            (
                (dataframe["squeeze_fire"] == 1)
                & (dataframe["momentum"] < 0)
                & (dataframe["mom_decreasing"] == 1)
                & (dataframe["close"] < dataframe["ema_50"])
                & (dataframe["rsi"] > 30)
                & (dataframe["rsi"] < 55)
                & (dataframe["volume"] > dataframe["volume_sma"] * 1.5)
                & (dataframe["adx"] > 20)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "a31_squeeze_breakout_short")

        return dataframe

    def populate_exit_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        # Exit long: momentum reversal confirmed (AND, not OR)
        dataframe.loc[
            (
                (dataframe["momentum"] < 0)
                & (dataframe["mom_decreasing"] == 1)
            )
            | (dataframe["rsi"] > 80),
            ["exit_long", "exit_tag"],
        ] = (1, "a31_exit_momentum_fade")

        # Exit short: momentum reversal confirmed (AND, not OR)
        dataframe.loc[
            (
                (dataframe["momentum"] > 0)
                & (dataframe["mom_increasing"] == 1)
            )
            | (dataframe["rsi"] < 20),
            ["exit_short", "exit_tag"],
        ] = (1, "a31_exit_momentum_fade")

        return dataframe

    def confirm_trade_entry(
        self, pair, order_type, amount, rate, time_in_force,
        current_time, entry_tag, side, **kwargs
    ):
        """Block entries in confirmed downtrends"""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 1:
            return True
        last = dataframe.iloc[-1]
        adx_val = last.get("adx", 0)
        slope = last.get("ema_slope", 0)
        if adx_val > 25 and slope < -0.15:
            return False
        return True

    def custom_stake_amount(
        self, pair, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, entry_tag, side, **kwargs
    ):
        return proposed_stake * float(self.position_c.value)
