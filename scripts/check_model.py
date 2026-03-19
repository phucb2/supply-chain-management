import mlflow
import os

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
client = mlflow.tracking.MlflowClient()

try:
    for mv in client.search_model_versions("name='eta-model'"):
        print(f"v{mv.version}  stage={mv.current_stage}  run_id={mv.run_id}")
except Exception as e:
    print(f"Error listing models: {e}")

try:
    model = mlflow.pyfunc.load_model("models:/eta-model/Production")
    print(f"Model loaded OK: {model.metadata}")
except Exception as e:
    print(f"Load failed: {e}")
