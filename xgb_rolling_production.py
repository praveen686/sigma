# %% [markdown]
# # XGBoost with Cross Validation and PCA

# %%
import numpy as np
import pandas as pd
from numba import njit
import vectorbtpro as vbt

vbt.settings.set_theme("dark")
vbt.settings.plotting["layout"]["width"] = 800
vbt.settings.plotting["layout"]["height"] = 200
import warnings

warnings.filterwarnings("ignore")
import matplotlib.pyplot as plt


from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import (
    Ridge,
    Lasso,
    ElasticNet,
    LinearRegression,
    LogisticRegression,
)
from sklearn.svm import SVR, SVC
from xgboost import XGBRegressor
from xgboost import plot_importance
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.model_selection import cross_val_score
from sklearn.ensemble import RandomForestClassifier

clf = RandomForestClassifier(random_state=42)  # random forest classifier
from joblib import dump, load


# %% [markdown]
# ### Modeling
# The class Splitter can also be helpful in cross-validating ML models. In particular, you can casually step upon a class SKLSplitter that acts as a regular cross-validator from scikit-learn by subclassing BaseCrossValidator. We'll demonstrate its usage on a simple classification problem of predicting the best entry and exit timings.
#
# Before we start, we need to decide on features and labels that should act as predictor and response variables respectively. Features are usually multi-columnar time-series DataFrames where each row contains multiple data points (one per column) that should predict the same row in labels. Labels are usually a single-columnar time-series Series that should be predicted. Ask yourself the following questions to easily come up with a decision:
#
# "How can the future performance be represented, preferably as a single number? Should it be the price at the next bar, the average price change over the next week, a vector of weights for rebalancing, a boolean containing a signal, or something else?"
# "What kind of data that encompasses the past performance is likely to predict the future performance? Should it be indicators, news sentiment index, past backtesting results, or something else?"
# "Which ML model can handle such a task?" (remember that most models are limited to just a couple of specific feature and label formats!)
# For the sake of an example, we'll fit a random forest classifier on all TA-Lib indicators stacked along columns to predict the binary labels generated by the label generator TRENDLB, where 1 means an uptrend and 0 means a downtrend. Sounds like fun 😌

# %% [markdown]
# Build a pipeline to impute and (standard-)normalize the data, [reduce the dimensionality](https://scikit-learn.org/stable/auto_examples/compose/plot_digits_pipe.html) of the features, as well as fit one of the [linear](https://scikit-learn.org/stable/modules/linear_model.html) models to predict the average price change over the next n bars (i.e., regression task!). Based on each prediction, you can then decide whether a position is worth opening or closing out.

# %% [markdown]
# # Helper functions
# Create dollar bars and add them to the original df

# %%


def dollar_bar_func(ohlc_df, dollar_bar_size):
    # Calculate dollar value traded for each row
    ohlc_df["DollarValue"] = ohlc_df["Close"] * ohlc_df["Volume"]

    # Calculate cumulative dollar value
    ohlc_df["CumulativeDollarValue"] = ohlc_df["DollarValue"].cumsum()

    # Determine the number of dollar bars
    num_bars = int(ohlc_df["CumulativeDollarValue"].iloc[-1] / dollar_bar_size)

    # Generate index positions for dollar bars
    bar_indices = [0]
    cumulative_value = 0
    for i in range(1, len(ohlc_df)):
        cumulative_value += ohlc_df["DollarValue"].iloc[i]
        if cumulative_value >= dollar_bar_size:
            bar_indices.append(i)
            cumulative_value = 0

    # Create a new dataframe with dollar bars
    dollar_bars = []
    for i in range(len(bar_indices) - 1):
        start_idx = bar_indices[i]
        end_idx = bar_indices[i + 1]

        dollar_bar = {
            "Open": ohlc_df["Open"].iloc[start_idx],
            "High": ohlc_df["High"].iloc[start_idx:end_idx].max(),
            "Low": ohlc_df["Low"].iloc[start_idx:end_idx].min(),
            "Close": ohlc_df["Close"].iloc[end_idx],
            "Volume": ohlc_df["Volume"].iloc[start_idx:end_idx].sum(),
            "Quote volume": ohlc_df["Quote volume"].iloc[start_idx:end_idx].sum(),
            "Trade count": ohlc_df["Trade count"].iloc[start_idx:end_idx].sum(),
            "Taker base volume": ohlc_df["Taker base volume"]
            .iloc[start_idx:end_idx]
            .sum(),
            "Taker quote volume": ohlc_df["Taker quote volume"]
            .iloc[start_idx:end_idx]
            .sum(),
        }

        if isinstance(ohlc_df.index, pd.DatetimeIndex):
            dollar_bar["Open Time"] = ohlc_df.index[start_idx]
            dollar_bar["Close Time"] = ohlc_df.index[end_idx] - pd.Timedelta(
                milliseconds=1
            )
        elif "Open Time" in ohlc_df.columns:
            dollar_bar["Open Time"] = ohlc_df["Open Time"].iloc[start_idx]
            dollar_bar["Close Time"] = ohlc_df["Open Time"].iloc[
                end_idx
            ] - pd.Timedelta(milliseconds=1)

        dollar_bars.append(dollar_bar)

    dollar_bars_df = pd.concat(
        [pd.DataFrame([bar]) for bar in dollar_bars], ignore_index=True
    )

    return dollar_bars_df


# Create a simple function to simplify the number so we can use it in our column names
def simplify_number(num):
    """
    Simplifies a large number by converting it to a shorter representation with a suffix (K, M, B).
    simplify_number(1000) -> 1K
    """
    suffixes = ["", "K", "M", "B"]
    suffix_index = 0

    while abs(num) >= 1000 and suffix_index < len(suffixes) - 1:
        num /= 1000.0
        suffix_index += 1

    suffix = suffixes[suffix_index] if suffix_index > 0 else ""
    simplified_num = f"{int(num)}{suffix}"

    return simplified_num


def merge_and_fill_dollar_bars(original_df, dollar_bars_df, dollar_bar_size):
    # Add prefix to column names in dollar bars dataframe
    dollar_bar_prefix = f"db_{simplify_number(dollar_bar_size)}_"
    dollar_bars_df_renamed = dollar_bars_df.add_prefix(dollar_bar_prefix)

    # Convert 'Open Time' columns to pandas datetime format and set them as index
    dollar_bars_df_renamed.index = pd.to_datetime(
        dollar_bars_df_renamed[dollar_bar_prefix + "Open Time"]
    )

    # Merge the dataframes on the index
    merged_df = original_df.merge(
        dollar_bars_df_renamed, how="left", left_index=True, right_index=True
    )

    # Set the flag for a new dollar bar with prefix
    merged_df[dollar_bar_prefix + "NewDBFlag"] = ~merged_df[
        dollar_bar_prefix + "Close"
    ].isna()

    # Forward fill the NaN values for all columns except the new dollar bar flag
    columns_to_ffill = [
        col for col in merged_df.columns if col != dollar_bar_prefix + "NewDBFlag"
    ]
    merged_df[columns_to_ffill] = merged_df[columns_to_ffill].fillna(method="ffill")

    # Fill the remaining NaN values in the new dollar bar flag column with False
    merged_df[dollar_bar_prefix + "NewDBFlag"] = merged_df[
        dollar_bar_prefix + "NewDBFlag"
    ].fillna(False)

    # Assign the renamed 'Open Time' column back to the dataframe
    merged_df[dollar_bar_prefix + "Open Time"] = merged_df[
        dollar_bar_prefix + "Open Time"
    ]

    return merged_df


# %% [markdown]
# # Calculate Dollar Bars
# Calc Dollar bars and then add technical analysis features
#
# Uncomment this section if you want to run different size dollar bars

# %%
# dollar_bar_size = 90_000_000
# btc_dollar_bars = dollar_bar_func(futures_1m.get(), dollar_bar_size=dollar_bar_size)
# btc_dollar_bars.index = pd.to_datetime(btc_dollar_bars['Open Time'])
# btc_dollar_bars.shape

# %%
# Convert the dataframe back into a vbt data object
# btc_90M_db_vbt = vbt.BinanceData.from_data(btc_dollar_bars)


# %%
# Save the dollarbars to a pickle file
# btc_90M_db_vbt.save('btc_90M_db_vbt.pkl')

# %% [markdown]
# # Load the dollar bars from pickle file

# %%
btc_90M_db_vbt = vbt.BinanceData.load("data/btc_90M_db_vbt.pkl")

# %% [markdown]
# Take a small slice of the data for train/testing and leave some to be out of sample

# %%
data = btc_90M_db_vbt["2021-01-01":"2023-01-01"]
outofsample_data = btc_90M_db_vbt["2023-01-01":"2023-06-03"]
print(data.shape)
print(outofsample_data.shape)

# %% [markdown]
# # Create the functions for the notebook


# %%
def prepare_data(
    data,
    pivot_up_th=0.30,
    pivot_down_th=0.05,
    periods_future=150,
    drop_cols=["Open Time", "Close Time"],
):
    """
    This function prepares the data for training the model.

    Parameters:
    data (DataFrame): The original DataFrame containing the data.
    pivot_up_th (float): Threshold for upward trend.
    pivot_down_th (float): Threshold for downward trend.
    periods_future (int): Number of periods in the future to predict.
    drop_cols (list): Columns to be dropped from the original DataFrame.

    Returns:
    X (DataFrame): The feature matrix.
    y (Series): The target vector.
    """

    # Generate the features (X) and target (y) dataframes
    X = data.get()
    # Get pivot information
    pivot_info = data.run("pivotinfo", up_th=pivot_up_th, down_th=pivot_down_th)
    binary_pivot_labels = np.where(
        data.close > pivot_info.conf_value, 1, 0
    )  # Create binary labels for pivot points
    X["trend"] = binary_pivot_labels  # add pivot label as a feature
    # Drop the time columns
    X = X.drop(drop_cols, axis=1)
    # Add time features
    X["dayofmonth"] = X.index.day
    X["month"] = X.index.month
    X["year"] = X.index.year
    X["hour"] = X.index.hour
    X["minute"] = X.index.minute
    X["dayofweek"] = X.index.dayofweek
    X["dayofyear"] = X.index.dayofyear

    # Now we are trying to generate future price predictions so we will set the y labels to the price change n periods in the future
    y = (
        (data.close.shift(-periods_future) / data.close - 1)
        .rolling(periods_future)
        .mean()
    )  # future price change we use rolling mean to smooth the data

    # Preprocessing steps to handle NaNs
    X = X.replace([-np.inf, np.inf], np.nan)  # replace inf with nan
    invalid_column_mask = X.isnull().all(axis=0)
    X = X.loc[:, ~invalid_column_mask]  # drop invalid columns
    invalid_row_mask = (
        X.isnull().any(axis=1) | y.isnull()
    )  # drop rows that have nan in any column or in y

    # Drop invalid rows in X and y
    X = X.loc[~invalid_row_mask]
    y = y.loc[~invalid_row_mask]

    return X, y


def create_pipeline(model="xgb"):
    """
    Create a scikit-learn pipeline.

    Parameters:
    model (str): The model to use in the pipeline. Default is 'xgb' (XGBoost).

    Returns:
    pipeline (Pipeline): The scikit-learn pipeline.
    """

    # Construct the pipeline
    steps = [
        (
            "imputation",
            SimpleImputer(strategy="mean"),
        ),  # Imputation replaces missing values
        ("scaler", StandardScaler()),  # StandardScaler normalizes the data
        # ('pca', PCA(n_components=15))  # PCA reduces dimensionality
    ]

    if model == "xgb":
        steps.append(
            ("model", XGBRegressor(objective="reg:squarederror", tree_method="gpu_hist"))
        )  # XGBoost regression is used as the prediction model
    elif model == "ridge":
        steps.append(("model", Ridge()))  # Ridge regression
    elif model == "linear":
        steps.append(("model", LinearRegression()))  # Linear regression
    elif model == "logistic":
        steps.append(("model", LogisticRegression()))  # Logistic regression
    elif model == "lasso":
        steps.append(("model", Lasso()))  # Lasso regression
    elif model == "elasticnet":
        steps.append(("model", ElasticNet()))  # ElasticNet regression
    elif model == "svr":
        steps.append(("model", SVR()))  # Support Vector Regression
    else:
        raise ValueError(
            "Invalid model name. Choose from 'xgb', 'ridge', 'linear', 'logistic', 'lasso', 'elasticnet', 'svr'."
        )

    pipeline = Pipeline(steps)

    return pipeline


def create_cv(X, min_length=600, offset=200, split=-200, set_labels=["train", "test"]):
    """
    Create a cross-validation splitter.

    Parameters:
    X (DataFrame): The feature matrix.
    min_length (int): The minimum length of a sample for cross-validation.
    offset (int): The offset used in cross-validation splitting.
    split (int): Index at which to split the data in cross-validation.
    set_labels (list): Labels for the train and test sets in cross-validation.

    Returns:
    cv_splitter (SKLSplitter): The cross-validation splits created from cv.get_splitter(X).
    cv (SKLSplitter): The cross-validation object.
    """

    # Cross-validate Creates a cross-validation object with all the indexes for each cv split
    cv = vbt.SKLSplitter(
        "from_expanding",
        min_length=min_length,
        offset=offset,
        split=split,
        set_labels=set_labels,
    )
    cv_splitter = cv.get_splitter(X)

    return cv_splitter, cv


def create_rolling_cv(X, length=2000, split=0.90, set_labels=["train", "test"]):
    """
    Create a cross-validation splitter.

    Parameters:
    X (DataFrame): The feature matrix.
    min_length (int): The minimum length of a sample for cross-validation.
    offset (int): The offset used in cross-validation splitting.
    split (int): Index at which to split the data in cross-validation.
    set_labels (list): Labels for the train and test sets in cross-validation.

    Returns:
    cv_splitter (SKLSplitter): The cross-validation splits created from cv.get_splitter(X).
    cv (SKLSplitter): The cross-validation object.
    """

    # Cross-validate Creates a cross-validation object with all the indexes for each cv split
    cv = vbt.SKLSplitter(
        "from_rolling", length=length, split=split, set_labels=set_labels
    )
    cv_splitter = cv.get_splitter(X)

    return cv_splitter, cv


def cross_validate_and_train(pipeline, X, y, cv_splitter, model_name=""):
    # Predictions
    X_slices = cv_splitter.take(X)
    y_slices = cv_splitter.take(y)

    test_labels = []
    test_preds = []
    for split in X_slices.index.unique(level="split"):
        X_train_slice = X_slices[(split, "train")]
        y_train_slice = y_slices[(split, "train")]
        X_test_slice = X_slices[(split, "test")]
        y_test_slice = y_slices[(split, "test")]
        pipeline.fit(X_train_slice, y_train_slice)
        test_pred = pipeline.predict(X_test_slice)
        test_pred = pd.Series(test_pred, index=y_test_slice.index)
        test_labels.append(y_test_slice)
        test_preds.append(test_pred)
        print(f"{model_name} Split {split} Mean Squared Error: {mean_squared_error(y_test_slice, test_pred)}")

    test_labels = pd.concat(test_labels).rename("labels")
    test_preds = pd.concat(test_preds).rename("preds")

    return pipeline, test_labels, test_preds


def evaluate_predictions(test_labels, test_preds, model_name=""):
    # Show the accuracy of the predictions
    mse = mean_squared_error(test_labels, test_preds)
    rmse = np.sqrt(mse)  # or use mean_squared_error with squared=False
    mae = mean_absolute_error(test_labels, test_preds)
    r2 = r2_score(test_labels, test_preds)

    print(f"{model_name} Mean Squared Error (MSE): {mse}")
    print(f"{model_name} Root Mean Squared Error (RMSE): {rmse}")
    print(f"{model_name} Mean Absolute Error (MAE): {mae}")
    print(f"{model_name} R-squared: {r2}")

    return mse, rmse, mae, r2


def extract_feature_importance(pipeline, X):
    """
    Extract the feature importance from a fitted XGBoost model in a pipeline.

    Parameters:
    pipeline (Pipeline): The fitted scikit-learn pipeline containing an XGBoost model.
    X (DataFrame): The feature matrix used to fit the pipeline.

    Returns:
    None.
    """

    # Extract the fitted XGBRegressor model from the pipeline
    fitted_model = pipeline.named_steps["model"]

    # Get feature importance
    importance = fitted_model.feature_importances_

    # Summarize feature importance
    for i, j in enumerate(importance):
        print("Feature: %0d, Score: %.5f" % (i, j))

    # Plot feature importance
    # plot_importance(fitted_model)
    # plt.show()

    # Assuming `X` is your feature matrix
    feature_names = X.columns.tolist()

    # If you use PCA in your pipeline, the output feature names would be the principal components, not the original feature names.
    # If that's the case, you should generate new names for the principal components
    if "pca" in pipeline.named_steps:
        n_components = pipeline.named_steps["pca"].n_components_
        feature_names = [f"PC{i+1}" for i in range(n_components)]

    # Print feature importance with names
    for name, importance in zip(feature_names, fitted_model.feature_importances_):
        print(f"Feature: {name}, Score: {importance}")


# %% [markdown]
# # Prepare the insample data and out of sample data for training and testing
# Add features and pre process the data to make sure we have the same shapes and remove any problem columns

# %%
# Prep In Sample Data
X, y = prepare_data(data, pivot_up_th=0.10, pivot_down_th=0.10)
# Prep Out of Sample Data
Xoos, yoos = prepare_data(outofsample_data)


# %% [markdown]
# # Construct a pipeline and set up your cross validations

# %%
pipeline = create_pipeline(model="xgb")
cv_splitter, cv = create_rolling_cv(
    X, length=200, split=0.90, set_labels=["train", "test"]
)

# %%
# Train and cross-validate
final_pipeline, test_labels, test_preds = cross_validate_and_train(
    pipeline, X, y, cv_splitter, model_name="In-Sample"
)

# Evaluate
mse, rmse, mae, r2 = evaluate_predictions(
    test_labels, test_preds, model_name="In-Sample"
)

# %% [markdown]
# Save the model trained up to 2023 on "in sample" data using cross validation

# %%

filename = "models/model_upto_2023_rolling.joblib"
dump(pipeline, filename)

# %% [markdown]
# ### Load the model from storage

# %%
filename = "models/model_upto_2023_rolling.joblib"
# Load the model from the .joblib file
final_pipeline = load(filename)

# Make predictions on the entire dataset
insample_predictions = final_pipeline.predict(X)
insample_predictions = pd.Series(insample_predictions, index=y.index)
# Calculate the R-squared score on the entire dataset
r2 = r2_score(y, insample_predictions)
print(
    "This is how well the model is at fitting to the original data it was trained and tested on"
)
print(f"R-squared on the entire dataset: {r2}")


# %% [markdown]
# #### Check out the fit on in sample data

# %%
# Visualize the predictions versus the actuals
# yoos is the actuals and outofsample_predictions is the predictions
# plt.scatter(y, insample_predictions, alpha=0.2)
# Add a line of best fit
# m, b = np.polyfit(y, insample_predictions, 1)
# plt.plot(y, m * y + b, color="red")

# # Add the formula for the slope and intercept
# plt.text(0.05, 0.95, f"y = {m:.2f}x + {b:.2f}", transform=plt.gca().transAxes)

# # Add the y and x axis labels
# plt.xlabel("Actuals")
# plt.ylabel("Predictions")

# %% [markdown]
# # Walk Forward Cross Validation on Out of sample data
# #### Retrain the model every 200 bars
# - Load the model
# - Preprocess the data
# - Create Cross Validations for training and testing on newly seen data
# - Train the model
# - Make predictions
# - Test and evaluate the model

# %%
filename = "models/model_upto_2023_rolling.joblib"
# Load the model from the .joblib file
final_pipeline = load(filename)

# Create your cross validation splits
cv_splitter_oos, cv_oos = create_rolling_cv(
    Xoos, length=200, split=0.9, set_labels=["train", "test"]
)

# Train and cross-validate
final_pipeline, oos_test_labels, oos_test_preds = cross_validate_and_train(
    final_pipeline, Xoos, yoos, cv_splitter_oos, model_name="Out-Of-Sample"
)

# Evaluate
mse, rmse, mae, r2 = evaluate_predictions(
    oos_test_labels, oos_test_preds, model_name="Out-Of-Sample"
)


# %%
# Save the model
total_filename = "models/out_of_sample_rolling.joblib"
dump(final_pipeline, total_filename)

# %% [markdown]
# ### Simulate a portfolio in 2023 with retraining the model every 200 bars

# %%
oos_retraining_pf = vbt.Portfolio.from_signals(
    outofsample_data.close[oos_test_preds.index],  # use only the test set
    entries=oos_test_preds > 0.05,  # long entry when prediction is greater than X%
    exits=oos_test_preds < 0.00,  # exit long when prediction is negative
    short_entries=oos_test_preds
    < -0.04,  # enter short when prediction is less than -X%
    short_exits=oos_test_preds > 0.0,  # exit short when prediction is positive
    # direction="both" # long and short
)
print(oos_retraining_pf.stats())


# %%
# oos_retraining_pf.plot().show()

# %% [markdown]
# 👆 better drawdowns than a buy and hold, and almost the same results.

# %% [markdown]
# # Look at the Portfolio on Test Data

# %% [markdown]
# and Simulate a portfolio?

# %%
insample_pf = vbt.Portfolio.from_signals(
    data.close[test_preds.index],  # use only the test set
    entries=test_preds
    > 0.0,  # long when probability of price increase is greater than 2%
    exits=test_preds
    < 0.00,  # long when probability of price increase is greater than 2%
    short_entries=test_preds
    < 0.0,  # long when probability of price increase is greater than 2%
    short_exits=test_preds > 0.0,  # short when probability prediction is less than -5%
    # direction="both" # long and short
)
print(insample_pf.stats())

# pf.plot().show_svg()
# Show first period
# pf['2018':'2021'].plot().show_svg()
# Show second period
# pf['2021':'2023'].plot().show_svg()


# %%
# insample_pf.plot().show()

# %%
insample_pf.orders.records_readable

# %%
insample_pf.trades.records_readable

# %% [markdown]
#

# %% [markdown]
# # Comine insample with out of sample

# %%
# fig = insample_pf.cumulative_returns.vbt.plot(
#     trace_kwargs=dict(name="Insample")
# )  # plot the in sample equity curve from test data not trained data
# oos = (
#     insample_pf.cumulative_returns[-1] * (1 + oos_retraining_pf.returns).cumprod()
# )  # append the out of sample equity curve to the in sample equity curve
# # Add the out of sample equity curve to the plot
# oos.vbt.plot(fig=fig, trace_kwargs=dict(name="Out of Sample"))
# normalized_price = data.close / data.close[0]
# oos_normalized_price = (
#     outofsample_data.close / outofsample_data.close[0] * normalized_price[-1]
# )  # normalize the out of sample data to the last price of the in sample data
# normalized_price.rename("Normalized Price").vbt.plot(fig=fig)
# oos_normalized_price.rename("Out of Sample Normalized Price").vbt.plot(fig=fig)
# # The gap is the warmup period for the new model to start making predictions

# %% [markdown]
# ## Save everything to the models folder for later analysis

# %%
insample_pf.save("models/insample_test_portfolio_rolling.pkl")
insample_pf.stats().to_csv("models/insample_stats_test_rolling.csv")
insample_pf.trades.records_readable.to_csv("models/insample_trades_test_rolling.csv")
test_preds.to_csv("models/insample_preds_test_rolling.csv")
X.to_csv("models/insample_X_test_rolling.csv")
y.to_csv("models/insample_y_test_rolling.csv")
Xoos.to_csv("models/oos_X_test_rolling.csv")
yoos.to_csv("models/oos_y_test_rolling.csv")
oos_test_preds.to_csv("models/oos_preds_test_rolling.csv")
oos_retraining_pf.save("models/oos_retrained_portfolio_rolling.pkl")
oos_retraining_pf.stats().to_csv("models/oos_retrained_stats_rolling.csv")
oos_retraining_pf.trades.records_readable.to_csv(
    "models/oos_retrained_trades_rolling.csv"
)

# %% [markdown]
# # Explore which features are impacting the model

# %%


extract_feature_importance(final_pipeline, X)


# %% [markdown]
# A lot to unpack up above. Why are the feature scores so much different than the fscores of the features?

# %% [markdown]
# # Hyperparameter Tuning

# %% [markdown]
# ### Randomized Search

# %%
from sklearn.model_selection import RandomizedSearchCV
from scipy.stats import uniform, randint

# Specify hyperparameters to tune and their respective distributions
param_dist = {
    "model__learning_rate": uniform(0.01, 0.2),
    "model__n_estimators": randint(100, 1000),
    "model__max_depth": randint(3, 10),
    "model__min_child_weight": randint(1, 10),
    "model__subsample": uniform(0.5, 0.5),
    "model__colsample_bytree": uniform(0.5, 0.5),
    # add other parameters here
}

# Perform randomized search
random_search = RandomizedSearchCV(
    pipeline,
    param_dist,
    n_iter=10,
    cv=cv,
    scoring="neg_mean_squared_error",
    n_jobs=-1,
    verbose=10,
    random_state=42,
)
random_search.fit(X, y)

# Best parameters and score from random search
print(f"Best parameters: {random_search.best_params_}")
print(f"Best score: {random_search.best_score_}")


# %%
cv_splitter, cv = create_rolling_cv(X, length=200, split=0.9)

# The slices are obtained by using your cv_splitter on your X and y.
X_slices = cv_splitter.take(X)
y_slices = cv_splitter.take(y)

# Fit and predict with the best estimator
test_labels = []
test_preds = []
for split in X_slices.index.unique(level="split"):
    X_train_slice = X_slices[(split, "train")]
    y_train_slice = y_slices[(split, "train")]
    X_test_slice = X_slices[(split, "test")]
    y_test_slice = y_slices[(split, "test")]

    slice_pipeline = random_search.best_estimator_.fit(
        X_train_slice, y_train_slice
    )  # uses the best estimator from the random search
    test_pred = slice_pipeline.predict(X_test_slice)
    test_pred = pd.Series(test_pred, index=y_test_slice.index)
    test_labels.append(y_test_slice)
    test_preds.append(test_pred)
    print(f"MSE for split {split}: {mean_squared_error(y_test_slice, test_pred)}")


test_labels = pd.concat(test_labels).rename("labels")
test_preds = pd.concat(test_preds).rename("preds")
test_preds.to_csv("models/hyperopt/test_preds_rolling.csv") # TODO: Joel you may need to create a folder
# Show the accuracy of the predictions
# Assuming test_labels and test_preds are your true and predicted values
mse = mean_squared_error(test_labels, test_preds)
rmse = np.sqrt(mse)  # or use mean_squared_error with squared=False
mae = mean_absolute_error(test_labels, test_preds)
r2 = r2_score(test_labels, test_preds)

print(f"hyper opt Mean Squared Error (MSE): {mse}")
print(f"hyper opt Root Mean Squared Error (RMSE): {rmse}")
print(f"hyper opt Mean Absolute Error (MAE): {mae}")
print(f"hyper opt R-squared: {r2}")

# Visualize the predictions as a heatmap plotted against the price
# data.close.vbt.overlay_with_heatmap(test_preds).show_svg()

# %%
# Save the model with the best parameters
import json

# Save the model with the best parameters
dump(random_search.best_estimator_, "models/hyperopt/xgboost_best_estimator_rolling.joblib")

# Save best params dictionary
with open("models/hyperopt/xgboost_best_params_rolling.json", "w") as fp:
    json.dump(random_search.best_params_, fp)


# %%

hyperopt_pf = vbt.Portfolio.from_signals(
    data.close[test_preds.index],  # use only the test set
    entries=test_preds
    > 0.05,  # long when probability of price increase is greater than 2%
    exits=test_preds
    < 0.00,  # long when probability of price increase is greater than 2%
    short_entries=test_preds
    < -0.04,  # long when probability of price increase is greater than 2%
    short_exits=test_preds > 0.0,  # short when probability prediction is less than -5%
    # direction="both" # long and short
)
print(hyperopt_pf.stats())
# hyperopt_pf.plot().show()
hyperopt_pf.save("models/hyperopt/hyperopt_pf_rolling.pkl")
hyperopt_pf.trades.records_readable.to_csv("models/hyperopt/hyperopt_trades_rolling.csv")
hyperopt_pf.orders.records_readable.to_csv("models/hyperopt/hyperopt_orders_rolling.csv")
hyperopt_pf.stats().to_csv("models/hyperopt/hyperopt_pf_stats_rolling.csv")
#TODO Joel you may need to create a folder and save all the other files like trades etc. 
# %% [markdown]
# ### Grid Search Method
# #### DONT RUN WITHOUT GPU

# %%
# from sklearn.model_selection import GridSearchCV

# # Specify hyperparameters to tune and their respective ranges
# param_grid = {
#     "model__learning_rate": [0.01, 0.1, 0.2],
#     "model__n_estimators": [100, 500, 1000],
#     "model__max_depth": [3, 5, 7],
#     "model__min_child_weight": [1, 5, 10],
#     "model__subsample": [0.5, 0.7, 1.0],
#     "model__colsample_bytree": [0.5, 0.7, 1.0]
#     # add other parameters here
# }

# # Perform grid search
# grid_search = GridSearchCV(
#     pipeline, param_grid, cv=cv, scoring="r2", n_jobs=-1, verbose=10
# )
# grid_search.fit(X, y)

# # Best parameters and score from grid search
# print(f"Best parameters: {grid_search.best_params_}")
# print(f"Best score: {grid_search.best_score_}")


# %%
# cv_splitter, cv = create_cv(X, min_length=600, offset=200, split=-200)

# # The slices are obtained by using your cv_splitter on your X and y.
# X_slices = cv_splitter.take(X)
# y_slices = cv_splitter.take(y)

# # Here, we train the model using the slices and the best estimator from your RandomizedSearchCV
# test_labels, test_preds, final_pipeline = cross_validate_and_train(random_search.best_estimator_, X_slices, y_slices, cv_splitter, model_name="Random Search Best Estimator")

# # And now we evaluate the predictions.
# mse, rmse, mae, r2 = evaluate_predictions(test_labels, test_preds, model_name="Random Search Best Estimator")


# %%
# pf = vbt.Portfolio.from_signals(
#     data.close[test_preds.index],  # use only the test set
#     entries=test_preds > 0.05,  # long when prediction > X%
#     exits=test_preds < 0.00,  # exit when prediction is negative
#     short_entries=test_preds < -0.05,  # short when prediction < -X%
#     short_exits=test_preds > 0.00,  # exit when prediction is positive
# )
# print(pf.stats())
# pf.plot().show()


# %%
# pf.trades.records_readable

# %%
