def aggregate_updates(updates):
    total_samples = sum(update["samples"] for update in updates)
    if total_samples <= 0:
        raise ValueError("Positive sample counts are required")
    return [
        sum(update["weights"][index] * update["samples"] for update in updates) / total_samples
        for index in range(len(updates[0]["weights"]))
    ]