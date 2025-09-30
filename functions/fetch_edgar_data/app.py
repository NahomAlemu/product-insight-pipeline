import json
import urllib.request
import urllib.error
import os
import boto3  # pyright: ignore[reportMissingImports]

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
s3 = boto3.client("s3")

# SEC requires a custom User-Agent for all API requests
HEADERS = {"User-Agent": "AccountRoiCopilot/1.0 (youremail@gmail.com)"}

def _http_get(url):
    """Performs a GET request with the required SEC headers."""
    req = urllib.request.Request(url, headers=HEADERS)
    # This will automatically raise an HTTPError for 4xx/5xx responses
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def handler(event, context):
    """
    Fetches company facts and submissions, saves them to S3,
    and returns S3 paths (the "claim check").
    """
    print(f"Fetching data for event: {json.dumps(event)}")
    account = event.get("account", {})
    cik = account.get("cik")

    if not cik:
        raise ValueError("Missing 'cik' in account object")

    cik_padded = str(cik).zfill(10)
    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    # This try/except block will now catch any network or HTTP errors
    try:
        print(f"Fetching and saving facts for CIK {cik}")
        facts_content_bytes = _http_get(facts_url)
        facts_key = f"intermediate/{cik}-facts.json"
        s3.put_object(Bucket=OUTPUT_BUCKET, Key=facts_key, Body=facts_content_bytes)
        
        print(f"Fetching and saving submissions for CIK {cik}")
        submissions_content_bytes = _http_get(submissions_url)
        submissions_key = f"intermediate/{cik}-submissions.json"
        s3.put_object(Bucket=OUTPUT_BUCKET, Key=submissions_key, Body=submissions_content_bytes)

        # On success, return the "claim check" object
        return {
            "status": "success",
            "cik": cik,
            "s3_references": {
                "facts_key": facts_key,
                "submissions_key": submissions_key
            }
        }
    except Exception as e:
        # If any error occurs (e.g., 404 from SEC), print it and re-raise it
        print(f"An error occurred fetching data for CIK {cik}: {str(e)}")
        # This will cause the Lambda to fail, correctly stopping the Step Function
        raise e