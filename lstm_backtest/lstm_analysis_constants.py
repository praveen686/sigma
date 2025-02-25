from enum import Enum

class ActionType(str, Enum):
  OPEN_SHORT          = "open-short"
  OPEN_LONG           = "open-long"
  CLOSE_LONG          = "close-long"
  CLOSE_SHORT         = "close-short"
  LEGACY_OPEN_LONG    = "open_long"
  LEGACY_OPEN_SHORT   = "open_short"
  LEGACY_CLOSE_LONG   = "close_long"
  LEGACY_CLOSE_SHORT  = "close_short"
  NOOP                = "no_op"


class EntryType(str, Enum):
  LONG_ONLY           = "Long only"
  SHORT_ONLY          = "Short only"
  LONG_SHORT          = "Long and short"


LSTM_REVERSAL_EXITS_BACKTEST_RESULT_KEY           = "LSTM_only_reversal_exits"
LSTM_PREDICTION_WINDOW_EXITS_BACKTEST_RESULT_KEY  = "LSTM_only_prediction_window_exits"

BACKTEST_NAME               = "Name"
ENTRY_SLOPE_THRESHOLD       = "Entry Slope Threshold"
SHORT_ENTRY_SLOPE_THRESHOLD = "Short Entry Slope Threshold"
EXIT_SLOPE_THRESHOLD        = "Exit Slope Threshold"
SHORT_EXIT_SLOPE_THRESHOLD  = "Short Exit Slope Threshold"
LONG_MINUS_SHORT_THRESHOLD  = "Long Minus Short Threshold"
ENTRY_TYPE                  = "Entry Type"
VBT_TOTAL_RETURN            = "Total Return [%]"
VBT_WIN_RATE                = "Win Rate [%]"
VBT_TOTAL_TRADES            = "Total Trades"

