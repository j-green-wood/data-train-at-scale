import numpy as np
import pandas as pd

from google.cloud import bigquery
from pathlib import Path
from colorama import Fore, Style
from dateutil.parser import parse

from taxifare.params import *
from taxifare.ml_logic.data import clean_data
from taxifare.ml_logic.preprocessor import preprocess_features
from taxifare.ml_logic.registry import save_model, save_results, load_model
from taxifare.ml_logic.model import compile_model, initialize_model, train_model

def preprocess_and_train(min_date:str = '2009-01-01', max_date:str = '2015-01-01') -> None:
    """
    - Query the raw dataset from Le Wagon's BigQuery dataset
    - Cache query result as a local CSV if it doesn't exist locally
    - Clean and preprocess data
    - Train a Keras model on it
    - Save the model
    - Compute & save a validation performance metric
    """

    print(Fore.MAGENTA + "\n ⭐️ Use case: preprocess_and_train" + Style.RESET_ALL)

    min_date = parse(min_date).strftime('%Y-%m-%d') # e.g '2009-01-01'
    max_date = parse(max_date).strftime('%Y-%m-%d') # e.g '2009-01-01'

    query = f"""
        SELECT {",".join(COLUMN_NAMES_RAW)}
        FROM `{GCP_PROJECT_WAGON}`.{BQ_DATASET}.raw_{DATA_SIZE}
        WHERE pickup_datetime BETWEEN '{min_date}' AND '{max_date}'
        ORDER BY pickup_datetime
        """

    # Retrieve `query` data from BigQuery or from `data_query_cache_path` if the file already exists!
    data_query_cache_path = Path(LOCAL_DATA_PATH).joinpath("raw", f"query_{min_date}_{max_date}_{DATA_SIZE}.csv")
    data_query_cached_exists = data_query_cache_path.is_file()

    if data_query_cached_exists:
        print("Loading data from local CSV...")

        data = pd.read_csv(data_query_cache_path, parse_dates=['pickup_datetime'])

    else:
        print("Loading data from Querying Big Query server...")

        from google.cloud import bigquery

        client = bigquery.Client(project=GCP_PROJECT)
        query_job = client.query(query)
        result = query_job.result()
        data = result.to_dataframe(dtypes=DTYPES_RAW)

        # Save it locally to accelerate the next queries!
        data.to_csv(data_query_cache_path, header=True, index=False)

    # Clean data using data.py
    data = clean_data(data)

    # Create (X_train, y_train, X_val, y_val) without data leaks
    # No need for test sets, we'll report val metrics only
    split_ratio = 0.02 # About one month of validation data

    val_length = int((len(data)) * split_ratio)
    train_length = len(data) - val_length

    df_train = data.iloc[:train_length, :].sample(frac=1) # Shuffle datasets to improve training
    df_val = data.iloc[train_length: train_length + val_length, :].sample(frac=1)

    print(df_train.shape)
    print(df_val.shape)

    assert len(df_train) + len(df_val) == len(data)

    X = data.drop("fare_amount", axis=1)
    y = data[["fare_amount"]]

    X_train = df_train.drop("fare_amount", axis=1)
    y_train = df_train[["fare_amount"]]

    X_val = df_val.drop("fare_amount", axis=1)
    y_val = df_val[["fare_amount"]]

    # Create (X_train_processed, X_val_processed) using `preprocessor.py`
    # Luckily, our preprocessor is stateless: we can `fit_transform` both X_train and X_val without data leakage!

    X_train_processed = preprocess_features(X_train)
    X_val_processed = preprocess_features(X_val)

    # Train a model on the training set, using `model.py`
    # input_shape = X_train_processed.shape[1:]
    learning_rate = 0.0005
    batch_size = 256
    patience = 2

    model = initialize_model(input_shape=X_train_processed.shape[1:])
    model = compile_model(model, learning_rate=learning_rate)

    model, history = train_model(
        model,
        X_train_processed,
        y_train,
        batch_size=batch_size,
        patience=patience,
        validation_data=(X_val_processed, y_val))


    # Compute the validation metric (min val_mae) of the holdout set
    val_mae = np.min(history.history['val_mae'])

    # Save trained model
    params = dict(
        learning_rate=learning_rate,
        batch_size=batch_size,
        patience=patience
    )

    save_results(params=params, metrics=dict(mae=val_mae))
    save_model(model=model)

    print("✅ preprocess_and_train() done")


def pred(X_pred: pd.DataFrame = None) -> np.ndarray:
    print(Fore.MAGENTA + "\n ⭐️ Use case: pred" + Style.RESET_ALL)

    if X_pred is None:
        X_pred = pd.DataFrame(dict(
            pickup_datetime=[pd.Timestamp("2013-07-06 17:18:00", tz='UTC')],
            pickup_longitude=[-73.950655],
            pickup_latitude=[40.783282],
            dropoff_longitude=[-73.984365],
            dropoff_latitude=[40.769802],
            passenger_count=[1],
        ))

    model = load_model()
    X_processed = preprocess_features(X_pred)
    y_pred = model.predict(X_processed)

    print(f"✅ pred() done")

    return y_pred


if __name__ == '__main__':
    try:
        preprocess_and_train()
        # preprocess()
        # train()
        pred()
    except:
        import sys
        import traceback

        import ipdb
        extype, value, tb = sys.exc_info()
        traceback.print_exc()
        ipdb.post_mortem(tb)
