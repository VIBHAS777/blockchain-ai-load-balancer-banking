import os
import joblib
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC

from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, LabelEncoder


# ==============================
# PATH SETUP
# ==============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "anomaly_data.csv")  # change if needed
OUTPUT_DIR = BASE_DIR


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Loading anomaly dataset...")
    df = pd.read_csv(DATA_PATH)

    # ==============================
    # CHECK TARGET COLUMN
    # ==============================
    if "label" not in df.columns:
        raise ValueError("Dataset must contain 'label' column (normal/anomaly)")

    # Features & Labels
    X = df.drop(columns=["label"])
    y = df["label"]

    # Encode labels (0,1)
    encoder = LabelEncoder()
    y_enc = encoder.fit_transform(y)

    # Train/Test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
    )

    # ==============================
    # DEFINE 3 MODELS
    # ==============================
    models = {
        "LogisticRegression": LogisticRegression(max_iter=1000),
        "RandomForest": RandomForestClassifier(n_estimators=100, random_state=42),
        "SVM": SVC(kernel="rbf")
    }

    best_model = None
    best_score = 0
    best_name = ""

    print("\nTraining & comparing models...\n")

    # ==============================
    # MODEL SELECTION
    # ==============================
    for name, model in models.items():
        pipeline = make_pipeline(StandardScaler(), model)

        scores = cross_val_score(pipeline, X, y_enc, cv=5)
        mean_score = scores.mean()

        print(f"{name} CV Accuracy: {mean_score:.4f}")

        if mean_score > best_score:
            best_score = mean_score
            best_model = pipeline
            best_name = name

    # ==============================
    # TRAIN BEST MODEL
    # ==============================
    print(f"\nBest Model: {best_name} ({best_score:.4f})")

    best_model.fit(X_train, y_train)

    # ==============================
    # TEST EVALUATION
    # ==============================
    predictions = best_model.predict(X_test)

    accuracy = accuracy_score(y_test, predictions)
    print(f"\nTest Accuracy: {accuracy:.4f} ({accuracy:.2%})")

    print("\nClassification Report:")
    print(classification_report(y_test, predictions, target_names=encoder.classes_))

    # ==============================
    # SAVE BEST MODEL
    # ==============================
    joblib.dump(best_model, os.path.join(OUTPUT_DIR, "best_model.pkl"))
    joblib.dump(encoder, os.path.join(OUTPUT_DIR, "label_encoder.pkl"))

    print("\nSaved:")
    print("  best_model.pkl")
    print("  label_encoder.pkl")

    # ==============================
    # QUICK TEST
    # ==============================
    sample = X.iloc[:5]
    pred = encoder.inverse_transform(best_model.predict(sample))

    print("\nSample Predictions:")
    for i, p in enumerate(pred):
        print(f"Row {i}: {p}")


if __name__ == "__main__":
    main()