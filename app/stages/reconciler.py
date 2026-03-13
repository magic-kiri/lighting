import csv
import os


def reconcile_counts(
    pdfplumber_counts: dict[str, int],
    llm_counts: dict[str, int],
    threshold: int = 2,
) -> list[dict]:
    """Compare pdfplumber and LLM counts, assign confidence."""
    all_types = sorted(set(list(pdfplumber_counts.keys()) + list(llm_counts.keys())))
    results = []

    for type_code in all_types:
        pdf_count = pdfplumber_counts.get(type_code, 0)
        llm_count = llm_counts.get(type_code, 0)
        diff = abs(pdf_count - llm_count)

        # pdfplumber is the source of truth for quantity;
        # fall back to LLM only when pdfplumber found 0.
        quantity = pdf_count if pdf_count > 0 else llm_count

        if diff <= threshold:
            results.append({
                "type": type_code,
                "quantity": quantity,
                "confidence": "high",
                "note": "",
            })
        else:
            results.append({
                "type": type_code,
                "quantity": quantity,
                "confidence": "review",
                "note": f"pdfplumber={pdf_count}, llm={llm_count}",
            })

    return results


def write_csv(results: list[dict], output_path: str) -> str:
    """Write results to CSV file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["type", "quantity", "confidence", "note"])
        writer.writeheader()
        writer.writerows(results)
    return output_path
