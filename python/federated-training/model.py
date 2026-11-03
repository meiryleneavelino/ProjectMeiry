import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split


ORGANIZATIONS = ("UVA", "VU", "TUDELFT")
FEATURES = ("feature_1", "feature_2", "feature_3", "feature_4")
ALGORITHM = "logistic-regression-v1"


def initial_model():
    return {"coefficients": [0.0] * len(FEATURES), "intercept": 0.0}


def generate_dataset(organization, destination):
    if organization not in ORGANIZATIONS:
        raise ValueError("Unknown organization")
    generator = np.random.default_rng(42 + ORGANIZATIONS.index(organization))
    features = generator.normal(0, 1, (240, len(FEATURES)))
    scores = features @ np.array([1.4, -1.0, 0.8, 0.3])
    labels = (scores + generator.normal(0, 0.45, len(features)) > 0).astype(int)
    target = Path(destination)
    if target.exists():
        raise ValueError("Dataset already exists; refusing to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(target, np.column_stack((features, labels)), delimiter=",",
               header=",".join((*FEATURES, "target")), comments="")


def prepare_dataset(organization, destination):
    if organization not in ORGANIZATIONS:
        raise ValueError("Unknown organization")
    target = Path(destination)
    if not target.exists():
        generate_dataset(organization, target)
    values = np.loadtxt(target, delimiter=",", skiprows=1)
    if (values.shape != (240, len(FEATURES) + 1) or not np.isfinite(values).all()
            or set(np.unique(values[:, -1])) != {0, 1}):
        raise ValueError("Invalid existing dataset; refusing to overwrite")


def train_local(dataset, global_model, epochs, round_number):
    values = np.loadtxt(dataset, delimiter=",", skiprows=1)
    features, labels = values[:, :-1], values[:, -1].astype(int)
    train_features, validation_features, train_labels, validation_labels = train_test_split(
        features, labels, test_size=0.2, random_state=17, stratify=labels)
    classifier = SGDClassifier(loss="log_loss", learning_rate="constant", eta0=0.03,
                               alpha=0.0001, random_state=round_number)
    classifier.partial_fit(np.zeros((2, len(FEATURES))), np.array([0, 1]), classes=[0, 1])
    classifier.coef_ = np.array([global_model["coefficients"]], dtype=float)
    classifier.intercept_ = np.array([global_model["intercept"]], dtype=float)
    for _ in range(epochs):
        classifier.partial_fit(train_features, train_labels)
    probabilities = classifier.predict_proba(validation_features)
    return {
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "samples": len(train_features),
        "accuracy": float(accuracy_score(validation_labels, classifier.predict(validation_features))),
        "validation_loss": float(log_loss(validation_labels, probabilities, labels=[0, 1])),
    }


def aggregate(updates):
    if not updates:
        raise ValueError("No updates to aggregate")
    total_samples = sum(update["samples"] for update in updates)
    if total_samples <= 0:
        raise ValueError("Sample counts must be positive")
    coefficients = np.zeros(len(FEATURES))
    intercept = 0.0
    for update in updates:
        weights = np.asarray(update["coefficients"], dtype=float)
        if weights.shape != (len(FEATURES),) or not np.isfinite(weights).all():
            raise ValueError("Invalid model coefficients")
        if update["samples"] <= 0 or not np.isfinite(update["intercept"]):
            raise ValueError("Invalid model update")
        fraction = update["samples"] / total_samples
        coefficients += weights * fraction
        intercept += update["intercept"] * fraction
    return {"coefficients": coefficients.tolist(), "intercept": float(intercept)}


def export_model(destination, global_model, organizations, rounds):
    artifact = {
        "format": "dynamos-logistic-regression-v1",
        "algorithm": ALGORITHM,
        "features": list(FEATURES),
        "classes": [0, 1],
        "organizations": organizations,
        "rounds": rounds,
        **global_model,
    }
    Path(destination).write_text(json.dumps(artifact, indent=2), encoding="utf-8")