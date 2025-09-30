import json
import os
import boto3  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone
import html

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]

def handler(event, context):
    """
    Generates an ROI brief using Bedrock, saves it to S3, and sends it via SES.
    Accepts either wrapped or unwrapped 'features' and supports bedrock.simulate for testing.
    """
    print(f"Generating brief for event: {json.dumps(event)}")

    # Unwrap features if necessary
    features_input = event.get("features") or {}
    if isinstance(features_input, dict) and "Payload" in features_input:
        features = features_input["Payload"]
    else:
        features = features_input

    bedrock_cfg = event.get("bedrock", {}) or {}
    ses_cfg = event.get("ses", {}) or {}

    if not features:
        raise ValueError("Features data is missing")

    # Simulation mode: if bedrock.simulate is True, return a deterministic fake output
    simulate_bedrock = bool(bedrock_cfg.get("simulate", False))

    # === 1. Construct prompt ===
    system_prompt = (
        "You are a Solutions Consultant at a B2B SaaS company like Highspot. Your task is to produce an ROI brief for a sales team. "
        "Your response MUST be a single, valid JSON object and nothing else. Do not include any text, preamble, or explanation before or after the JSON object. "
        "The JSON object must contain two top-level keys: 'json_data' and 'html_summary'."
    )

    user_prompt_content = f"""
Here is the financial data for the target account:
{json.dumps(features, indent=2)}

Based on this data, generate the ROI brief.
The 'json_data' object should contain fields like: account_name, fiscal_year, key_pain_points (a list of strings), value_hypothesis (a string), and next_best_action (a string).
The 'html_summary' should be a clean, professional HTML email body for the sales team.
"""

    # === 2. Invoke (or simulate) Bedrock ===
    if simulate_bedrock:
        print("Bedrock simulation mode enabled — building simulated output")
        simulated_json = {
            "json_data": {
                "account_name": features.get("company_name", "unknown"),
                "fiscal_year": features.get("fiscal_year"),
                "key_pain_points": ["Unclear sales enablement content", "Long rep ramp time"],
                "value_hypothesis": "Reduce ramp time and improve win-rate by improving content findability and guided plays.",
                "next_best_action": "Run a 30-day pilot with 3 sales teams."
            },
            "html_summary": f"<html><body><h1>Simulated ROI Brief: {html.escape(features.get('company_name','unknown'))}</h1>"
                            f"<p>Key hypothesis and actions.</p></body></html>"
        }
        llm_output = simulated_json
    else:
        # Real Bedrock call
        model_id = bedrock_cfg.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        region = bedrock_cfg.get("region", os.environ.get("AWS_REGION", "us-west-2"))

        br_client = boto3.client("bedrock-runtime", region_name=region)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt_content}]}],
            "max_tokens": int(bedrock_cfg.get("max_tokens", 1500)),
            "temperature": float(bedrock_cfg.get("temperature", 0.3)),
        }

        print("Invoking Bedrock model...")
        invoke = br_client.invoke_model(
            modelId=model_id,
            body=json.dumps(body).encode("utf-8"),
            contentType="application/json",
            accept="application/json"
        )
        response_body = json.loads(invoke.get("body").read())
        print(f"Bedrock response keys: {list(response_body.keys())}")

        # Extract the text, then resiliently parse JSON
        llm_output_str = ""
        # Some responses have "content" list, some may embed differently — be defensive
        if "content" in response_body and isinstance(response_body["content"], list):
            for block in response_body["content"]:
                if block.get("type") == "text":
                    llm_output_str += block.get("text", "")
        else:
            # Fallback: try to stringify top-level text
            llm_output_str = json.dumps(response_body)

        print(f"LLM raw output (preview): {llm_output_str[:400]}")

        try:
            llm_output = json.loads(llm_output_str.strip())
        except json.JSONDecodeError:
            print("WARNING: LLM output was not valid JSON. Falling back to embedding output into HTML summary.")
            # Safe fallback: embed the raw LLM text into html_summary to avoid failure
            llm_output = {
                "json_data": {},
                "html_summary": f"<html><body><h1>LLM output (non-JSON)</h1><pre>{html.escape(llm_output_str)}</pre></body></html>"
            }

    # === 3. Save artifacts to S3 ===
    s3 = boto3.client("s3")
    company_name = features.get("company_name", "unknown").lower().replace(" ", "-")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    s3_key_html = f"{today_str}/{company_name}-brief.html"
    s3_key_json = f"{today_str}/{company_name}-data.json"

    s3.put_object(Bucket=OUTPUT_BUCKET, Key=s3_key_html, Body=llm_output.get("html_summary", "").encode('utf-8'), ContentType='text/html')
    s3.put_object(Bucket=OUTPUT_BUCKET, Key=s3_key_json, Body=json.dumps(llm_output.get("json_data", {}), indent=2).encode('utf-8'), ContentType='application/json')
    print(f"Saved artifacts to s3://{OUTPUT_BUCKET}/{today_str}/")

    # === 4. Send Email Notification (optional) ===
    sender = ses_cfg.get("sender")
    recipient = ses_cfg.get("recipient")
    subject = f"Account ROI Brief: {features.get('company_name', 'N/A')}"

    if not sender or not recipient:
        raise ValueError("SES sender or recipient missing")

    ses_client = boto3.client("ses")
    ses_client.send_email(
        Source=sender,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": llm_output.get("html_summary", "<p>Error generating HTML.</p>"), "Charset": "UTF-8"}}
        }
    )
    print(f"Email sent successfully to {recipient}")

    return {"status": "success", "s3_path": f"s3://{OUTPUT_BUCKET}/{today_str}/"}
