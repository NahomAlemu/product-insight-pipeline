import json
import os
import boto3  # pyright: ignore[reportMissingImports]

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
s3 = boto3.client("s3")

def get_latest_fact(facts_data, fact_name, fiscal_year=None):
    """
    Extracts the most recent value for a specific financial fact (e.g., 'Revenues').
    Safer: checks presence of keys and presence of 'USD' unit.
    """
    try:
        facts = facts_data.get("facts", {}).get("us-gaap", {})
        if fact_name not in facts:
            return None, None

        units = facts[fact_name].get("units", {})
        if "USD" not in units:
            return None, None

        fact_list = units["USD"]
        # Filter for annual filings only (10-K)
        annual_filings = [f for f in fact_list if "frame" in f and f.get("form") == "10-K"]

        if not annual_filings:
            # fallback to any annual-like entries if no explicit 10-K
            if fact_list:
                fact_list_sorted = sorted(fact_list, key=lambda x: x.get("fy", 0), reverse=True)
                candidate = fact_list_sorted[0]
                return candidate.get("val"), candidate.get("fy")
            return None, None

        # Sort by fiscal year descending
        annual_filings.sort(key=lambda x: x.get("fy", 0), reverse=True)

        target_filing = annual_filings[0]
        if fiscal_year:
            found = next((f for f in annual_filings if f.get("fy") == fiscal_year), None)
            if found:
                target_filing = found
            else:
                return None, None

        return target_filing.get("val"), target_filing.get("fy")
    except Exception:
        return None, None

def handler(event, context):
    """
    Reads data from S3 using the "claim check" and calculates KPIs.
    Accepts both wrapped and unwrapped edgar_data objects.
    """
    print(f"Building features for event: {json.dumps(event)}")

    # Accept either wrapped or unwrapped Lambda output
    edgar_obj = event.get("edgar_data") or {}
    if isinstance(edgar_obj, dict) and "Payload" in edgar_obj:
        edgar_obj = edgar_obj["Payload"]

    # Backwards compatible: some inputs may pass s3_references directly
    s3_refs = edgar_obj.get("s3_references") or edgar_obj.get("s3_references", {})
    # Also accept top-level s3_references
    if not s3_refs:
        s3_refs = event.get("s3_references", {}) or {}

    facts_key = s3_refs.get("facts_key")
    submissions_key = s3_refs.get("submissions_key")

    if not facts_key or not submissions_key:
        raise ValueError("Missing S3 references in the event payload")

    facts_obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=facts_key)
    facts_data = json.loads(facts_obj["Body"].read().decode('utf-8'))

    submissions_obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=submissions_key)
    submissions_data = json.loads(submissions_obj["Body"].read().decode('utf-8'))

    cik = event.get("cik") or edgar_obj.get("cik")
    name = event.get("name")

    # --- Attempt to get the latest revenue and year ---
    latest_revenue, year = get_latest_fact(facts_data, "Revenues")

    # --- Initialize derived KPIs to None ---
    yoy_revenue_growth = None
    sm_as_pct_revenue = None

    # --- Only proceed with calculations if the initial lookup was successful ---
    if year is not None and latest_revenue is not None:
        prev_revenue, _ = get_latest_fact(facts_data, "Revenues", fiscal_year=year - 1)
        latest_sm_expense, _ = get_latest_fact(facts_data, "SalesAndMarketingExpense", fiscal_year=year)

        # Calculate YoY growth if possible
        if latest_revenue is not None and prev_revenue is not None and prev_revenue > 0:
            try:
                yoy_revenue_growth = (latest_revenue - prev_revenue) / prev_revenue
            except Exception:
                yoy_revenue_growth = None

        # Calculate S&M expense as a percentage of revenue if possible
        if latest_revenue is not None and latest_sm_expense is not None and latest_revenue > 0:
            try:
                sm_as_pct_revenue = latest_sm_expense / latest_revenue
            except Exception:
                sm_as_pct_revenue = None

    sic_description = submissions_data.get("sicDescription", "N/A")
    fiscal_year_end = submissions_data.get("fiscalYearEnd", "N/A")

    features = {
        "company_name": name,
        "cik": cik,
        "fiscal_year": year,  # May be None
        "industry": sic_description,
        "fiscal_year_end": fiscal_year_end,
        "latest_revenue_usd": latest_revenue,
        "yoy_revenue_growth_pct": round(yoy_revenue_growth * 100, 2) if yoy_revenue_growth is not None else None,
        "sm_expense_as_pct_revenue": round(sm_as_pct_revenue * 100, 2) if sm_as_pct_revenue is not None else None,
        "data_source": f"https://www.sec.gov/edgar/browse/?CIK={cik}"
    }

    print(f"Generated features: {json.dumps(features)}")
    return features
