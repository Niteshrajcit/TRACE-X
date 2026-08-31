"""
Offline Training Script (Phase 2C -> Production Migration)

In a production environment, predictive models should not be trained
dynamically on API startup. Instead, they should be trained offline on a
data warehouse of historical fraud data, and the resulting model artifact
should be deployed alongside the API for fast inference.

This script demonstrates this process:
1. It connects to the database to pull historical rings.
2. It trains the Gradient Boosting Classifier on those rings.
3. It exports the trained model to `models/corridor_model.joblib`.

Usage:
    python scripts/train_and_export_model.py
"""
import os
import joblib
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.graph.corridor import train_corridor_classifier

def main():
    # Ensure the models directory exists
    models_dir = os.path.join(os.getcwd(), "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "corridor_model.joblib")

    print("Connecting to the database...")
    db: Session = SessionLocal()
    
    try:
        print("Pulling historical rings and training the Corridor predictor...")
        # Note: in this example we are using the synthetic training data generator
        # already in `train_corridor_classifier`. In a real production scenario,
        # you would replace `build_training_dataset` inside that function to query
        # your data warehouse instead.
        model, metrics = train_corridor_classifier(db)
        
        print(f"Training completed successfully.")
        print(f"Metrics: {metrics}")
        
        print(f"Exporting model artifact to {model_path}...")
        joblib.dump(model, model_path)
        print("Done. The TRACE-X API can now load this static artifact for inference.")
        
    except ValueError as e:
        print(f"\nError: Not enough data to train the model. {e}")
        print("Please ensure your database contains historical fraud rings before training.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
