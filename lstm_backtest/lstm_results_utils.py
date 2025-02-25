import pandas as pd
import vectorbtpro as vbt
from typing import Dict, List
from lstm_analysis_constants import BACKTEST_NAME, ENTRY_SLOPE_THRESHOLD, ENTRY_TYPE, EXIT_SLOPE_THRESHOLD, LONG_MINUS_SHORT_THRESHOLD, SHORT_ENTRY_SLOPE_THRESHOLD, SHORT_EXIT_SLOPE_THRESHOLD, VBT_TOTAL_RETURN, VBT_WIN_RATE, VBT_TOTAL_TRADES
from prediction_window_slopes import PredictionWindowSlopes

def _print_one_backtest_results(values: Dict):  
  print(f"--------{values[BACKTEST_NAME]}--------")
  print(f"{VBT_TOTAL_RETURN}: {values[VBT_TOTAL_RETURN] :.2f}")
  print(f"{VBT_WIN_RATE}: {values[VBT_WIN_RATE] :.2f}")
  print(f"{VBT_TOTAL_TRADES}: {values[VBT_TOTAL_TRADES]}")



def create_empty_results_df() -> pd.DataFrame:
  data = {
    BACKTEST_NAME     : [],
    VBT_TOTAL_RETURN  : [],
    VBT_WIN_RATE      : [],
    VBT_TOTAL_TRADES  : []
  }

  return pd.DataFrame(data)



def store_backtest_results(name: str, pf: vbt.Portfolio, results: List[Dict[str, any]], slopes: PredictionWindowSlopes = None, should_print: bool = False):
  values: Dict[str, any]    = {}

  values[BACKTEST_NAME              ] = name
  values[ENTRY_TYPE                 ] = slopes.entry_type                   if slopes is not None and slopes.entry_type                   is not None else None
  values[ENTRY_SLOPE_THRESHOLD      ] = slopes.entry_slope_threshold        if slopes is not None and slopes.entry_slope_threshold        is not None else None
  values[SHORT_ENTRY_SLOPE_THRESHOLD] = slopes.short_entry_slope_threshold  if slopes is not None and slopes.short_entry_slope_threshold  is not None else None
  values[EXIT_SLOPE_THRESHOLD       ] = slopes.exit_slope_threshold         if slopes is not None and slopes.exit_slope_threshold         is not None else None
  values[SHORT_EXIT_SLOPE_THRESHOLD ] = slopes.short_exit_slope_threshold   if slopes is not None and slopes.short_exit_slope_threshold   is not None else None
  values[LONG_MINUS_SHORT_THRESHOLD ] = slopes.long_minus_short_threshold   if slopes is not None and slopes.long_minus_short_threshold   is not None else None  
  values[VBT_TOTAL_RETURN           ] = pf.total_return * 100.0
  values[VBT_WIN_RATE               ] = pf.trades.win_rate * 100.0
  values[VBT_TOTAL_TRADES           ] = pf.trades.count()

  results.append(values)
      
  if should_print:
    _print_one_backtest_results(values)



def export_results(results: List[Dict[str, any]]) -> pd.DataFrame:
  return pd.DataFrame(results)

  