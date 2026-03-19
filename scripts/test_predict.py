import os
import mlflow
import pandas as pd

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5001"))
model = mlflow.pyfunc.load_model("models:/eta-model/Production")

features = {
    "carrier": "DHL",
    "channel": "shopify",
    "item_count": 2,
    "total_weight_kg": 5.0,
    "day_of_week": 2,
    "hour_of_day": 12,
}

df = pd.DataFrame([features])
print("Input DataFrame:")
print(df)
print(df.dtypes)

try:
    result = model.predict(df)
    print(f"\nPrediction: {result[0]:.2f} hours")
except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
