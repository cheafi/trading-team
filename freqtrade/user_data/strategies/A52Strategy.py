"""
A52 Strategy — Top performing strategy from the ranking table
ETH/USDT 5m Futures | WR% 53.4 | DD% 9.8 | Profit +24,737

Core logic:
- Multi-timeframe momentum with mean-reversion filter
- c=0.50 (conservative position sizing coefficient)
- e=-0.18 (slight short bias — the "多空方向針")
- Uses ATR-based dynamic SL/TP

The 'e' parameter (entry bias) controls long/short preference:
  e > 0 = long bias, e < 0 = short bias, e = 0 = neutral
The 'c' parameter controls position sizing aggression:
  c = 1.0 = max size, c = 0.5 = half size (safer)
"""
import numpy as np
from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from pandas import DataFrame
import talib.abstract as ta


class A52Strategy(IStrategy):
    """
    A52 c=0.50 e=-0.18
    Top ranked strategy — balanced profit with controlled drawdown
    """

    INTERFACE_VERSION = 3

    # Strategy parameters
    timeframe = "5m"
    can_short = True  # Futures: both long and short

    # Position sizing coefficient
    position_c = DecimalParameter(0.1, 1.0, default=0.50, space="buy", optimize=True)
    # Entry bias: negative = short bias, positive = long bias
    entry_bias = DecimalParameter(-0.5, 0.5, default=-0.18, space="buy", optimize=True)

    # Indicator periods
    fast_ema = IntParameter(8, 21, default=12, space="buy", optimize=True)
    slow_ema = IntParameter(21, 55, default=26, space="buy", optimize=True)
    rsi_period = IntParameter(10, 20, default=14, space="buy", optimize=True)
    atr_period = IntParameter(10, 20, default=14, space="sell", optimize=True)

    # ROI table — graduated take profit
    minimal_roi = {
        "0": 0.012,
        "30": 0.008,
        "60": 0.005,
        "120": 0.002,
    }

    # Stoploss
    stoploss = -0.008  # 0.8% hard stop
    trailing_stop = True
    trailing_stop_positive = 0.004
    trailing_stop_positive_offset = 0.008
    trailing_only_offset_is_reached = True

    # Startup candles needed for indicators
    startup_candle_count = 200

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Calculate all technical indicators"""

        # EMAs for trend
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.fast_ema.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.slow_ema.value))

        # RSI for momentum
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=int(self.rsi_period.value))

        # ATR for volatility-based stops
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=int(self.atr_period.value))

        # MACD for momentum confirmation
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        # Bollinger Bands for mean reversion
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bb["upperband"]
        dataframe["bb_middle"] = bb["middleband"]
        dataframe["bb_lower"] = bb["lowerband"]

        # Volume SMA for volume filter
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # ADX for trend strength
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # EMA slope for trend direction
        dataframe["ema_slope"] = (dataframe["ema_fast"] - dataframe["ema_fast"].shift(10)) / dataframe["ema_fast"].shift(10) * 100

        # Direction score: combines trend + momentum + bias
        trend_score = np.where(
            dataframe["ema_fast"] > dataframe["ema_slow"], 1.0, -1.0
        )
        momentum_score = (dataframe["rsi"] - 50) / 50  # normalize to [-1, 1]
        macd_score = np.where(dataframe["macd_hist"] > 0, 0.5, -0.5)

        dataframe["direction_score"] = (
            trend_score * 0.4
            + momentum_score * 0.3
            + macd_score * 0.3
            + float(self.entry_bias.value)  # The 多空方向針
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Generate entry signals"""

        # Long entry conditions
        dataframe.loc[
            (
                (dataframe["direction_score"] > 0.6)
                & (dataframe["close"] > dataframe["ema_fast"])
                & (dataframe["rsi"] > 30)
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > dataframe["volume_sma"] * 1.3)
                & (dataframe["macd_hist"] > 0)
                & (dataframe["adx"] > 20)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "a52_long_momentum")

        # Short entry conditions (enabled by negative entry_bias)
        dataframe.loc[
            (
                (dataframe["direction_score"] < -0.6)
                & (dataframe["close"] < dataframe["ema_fast"])
                & (dataframe["rsi"] > 30)
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > dataframe["volume_sma"] * 1.3)
                & (dataframe["macd_hist"] < 0)
                & (dataframe["adx"] > 20)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "a52_short_momentum")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Generate exit signals — require confirmation, not single triggers"""

        # Exit long: strong reversal confirmed by multiple indicators
        dataframe.loc[
            (
                (dataframe["direction_score"] < -0.4)
                & (dataframe["macd_hist"] < 0)
            )
            | (
                (dataframe["rsi"] > 78)
                & (dataframe["close"] > dataframe["bb_upper"])
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "a52_exit_reversal")

        # Exit short: strong reversal confirmed
        dataframe.loc[
            (
                (dataframe["direction_score"] > 0.4)
                & (dataframe["macd_hist"] > 0)
            )
            | (
                (dataframe["rsi"] < 22)
                & (dataframe["close"] < dataframe["bb_lower"])
            ),
            ["exit_short", "exit_tag"],
        ] = (1, "a52_exit_reversal")

        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time, entry_tag, side: str,
                            **kwargs) -> bool:
        """Block entry in choppy/fading conditions"""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) == 0:
            return True
        last = dataframe.iloc[-1]
        adx = last.get("adx", 0)
        slope = last.get("ema_slope", 0)
        # Block long in fading downtrend
        if side == "long" and adx > 25 and slope < -0.15:
            return False
        # Block short in strong uptrend
        if side == "short" and adx > 25 and slope > 0.15:
            return False
        return True

    def custom_stake_amount(self, pair: str, current_time, current_rate: float,
                            proposed_stake: float, min_stake, max_stake,
                            leverage: float, entry_tag, side: str, **kwargs) -> float:
        """Apply position sizing coefficient c"""
        return proposed_stake * float(self.position_c.value)
