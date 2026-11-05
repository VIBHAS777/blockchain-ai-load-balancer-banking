import os
import joblib
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC

from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "server_data.xlsx")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Loading server selection data...")
    df = pd.read_excel(DATA_PATH)

    if "best_server" not in df.columns:
        raise ValueError("Training data must include a best_server label column")

    # Features & Labels
    feature_cols = [
        col for col in df.columns
        if col != "best_server" and not col.startswith("score_")
    ]

    X = df[feature_cols]
    y = df["best_server"]

    # Encode labels
    encoder = LabelEncoder()
    y_enc = encoder.fit_transform(y)

    # Train-Test split
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y_enc,
        test_size=0.2,
        random_state=42,
        stratify=y_enc,
    )

    # ==============================
    # Define Multiple Models
    # ==============================
    models = {
        "LogisticRegression": LogisticRegression(max_iter=1000),
        "RandomForest": RandomForestClassifier(n_estimators=100, random_state=42),
        "SVM": SVC(kernel="rbf")
    }

    best_model = None
    best_score = 0
    best_name = ""

    print("\nTraining and evaluating models...\n")

    # ==============================
    # Model Selection
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
    # Train Best Model
    # ==============================
    print(f"\nBest Model Selected: {best_name} ({best_score:.4f})")

    best_model.fit(X_train, y_train)

    # ==============================
    # Evaluation
    # ==============================
    predictions = best_model.predict(X_test)

    accuracy = accuracy_score(y_test, predictions)
    print(f"\nTest Accuracy: {accuracy:.4f} ({accuracy:.2%})")

    print("\nClassification Report:")
    print(classification_report(y_test, predictions, target_names=encoder.classes_))

    # ==============================
    # Save Best Model
    # ==============================
    joblib.dump(best_model, os.path.join(OUTPUT_DIR, "best_model.pkl"))
    joblib.dump(encoder, os.path.join(OUTPUT_DIR, "label_encoder.pkl"))

    # Save feature columns
    pd.Series(feature_cols).to_csv(
        os.path.join(OUTPUT_DIR, "feature_cols.csv"),
        index=False,
        header=False,
    )

    print(f"\nSaved artifacts to {OUTPUT_DIR}:")
    print("  best_model.pkl")
    print("  label_encoder.pkl")
    print("  feature_cols.csv")

    # ==============================
    # Inference Smoke Test
    # ==============================
    sample = X.iloc[:3].copy()
    predicted = encoder.inverse_transform(best_model.predict(sample))

    print("\nInference smoke sample:")
    for i, (pred_label, actual_label) in enumerate(zip(predicted, y.iloc[:3])):
        verdict = "ok" if pred_label == actual_label else "miss"
        print(f"  Row {i}: predicted={pred_label} actual={actual_label} {verdict}")


if __name__ == "__main__":
    main()