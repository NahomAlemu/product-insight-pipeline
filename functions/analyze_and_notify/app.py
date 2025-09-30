import json
import os
import boto3  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone

def _client(service, region=None):
    if region:
        return boto3.client(service, region_name=region)
    return boto3.client(service)

def handler(event, context):
    """
    event:
      {
        "aggregated": {
          "source_count": 3,
          "prompt_context": "..."
        },
        "bedrock": {
          "region": "us-west-2",
          "model_id": "anthropic.claude-3-sonnet-20240229-v1:0",
          "max_tokens": 2000,
          "temperature": 0.2
        },
        "ses": {
          "sender": "examplesender@gmail.com",
          "recipient": "examplereciver@gmail.com",
          "subject": "Daily Web Intel"
        }
      }
    """
    print("=== ANALYZE & NOTIFY FUNCTION STARTED ===")
    print(f"Full event received: {json.dumps(event, indent=2, default=str)}")
    
    try:
        agg = event.get("aggregated") or {}
        bedrock_cfg = event.get("bedrock") or {}
        ses_cfg = event.get("ses") or {}
        
        print(f"Aggregated data keys: {list(agg.keys())}")
        print(f"Bedrock config: {bedrock_cfg}")
        print(f"SES config: {ses_cfg}")

        # Handle Step Functions Lambda invocation response wrapper
        if "Payload" in agg:
            print("Found Payload wrapper - unwrapping Lambda response")
            agg_data = agg["Payload"]
        else:
            agg_data = agg

        prompt_context = agg_data.get("prompt_context", "")
        source_count = agg_data.get("source_count", 0)
        
        print(f"Source count: {source_count}")
        print(f"Prompt context length: {len(prompt_context)}")
        print(f"Prompt context preview: {prompt_context[:500]}...")

        # Temporarily allow empty sources for testing email functionality
        if not prompt_context:
            print("ERROR: No aggregated content to analyze - completely empty prompt_context")
            return {"error": "No aggregated content to analyze"}
        
        if source_count == 0:
            print("WARNING: source_count is 0, but continuing with base prompt for testing")
            # Add some test content so email sending can be tested
            prompt_context += "\n\n##### SOURCE 1\nURL: https://example.com\n----- BEGIN CONTENT -----\nThis is test content for pipeline testing.\n----- END CONTENT -----\n"

        print("=== BEDROCK SECTION ===")
        bedrock_region = bedrock_cfg.get("region") or os.getenv("BEDROCK_REGION", "us-west-2")
        
        # Handle CloudFormation variable that didn't get resolved
        if bedrock_region == "${AWS::Region}" or bedrock_region.startswith("${"):
            print(f"WARNING: Invalid region '{bedrock_region}', defaulting to us-west-2")
            bedrock_region = "us-west-2"
        model_id = bedrock_cfg.get("model_id") or "anthropic.claude-3-sonnet-20240229-v1:0"
        max_tokens = int(bedrock_cfg.get("max_tokens", 2000))
        temperature = float(bedrock_cfg.get("temperature", 0.2))

        print(f"Bedrock region: {bedrock_region}")
        print(f"Model ID: {model_id}")

        br = _client("bedrock-runtime", region=bedrock_region)
        print("Bedrock client created successfully")

        system_prompt = (
            "You are a senior research analyst. Write a crisp HTML email with:\n"
            "- Title with today's date\n"
            "- Executive summary in 5 to 8 bullets\n"
            "- Sections grouped by domain or topic\n"
            "- A short 'What to watch next' list\n"
            "Avoid hallucinations. If a claim is uncertain, mark it as unconfirmed.\n"
            "Use semantic <h2>, <h3>, <ul>, <li>, <p>, <table> when useful."
        )

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_context}
                    ]
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        print("About to invoke Bedrock model...")
        invoke = br.invoke_model(
            modelId=model_id,
            body=json.dumps(body).encode("utf-8"),
            contentType="application/json",
            accept="application/json"
        )
        print("Bedrock model invoked successfully")
        
        resp = json.loads(invoke.get("body").read())
        print(f"Bedrock response keys: {list(resp.keys())}")
        
        # Claude messages API returns content as a list of blocks
        llm_text = ""
        if "content" in resp and isinstance(resp["content"], list) and resp["content"]:
            for block in resp["content"]:
                if block.get("type") == "text":
                    llm_text += block.get("text", "")
        if not llm_text:
            llm_text = "<p>No response text produced.</p>"

        print(f"LLM response length: {len(llm_text)}")
        print(f"LLM response preview: {llm_text[:200]}...")

        # Wrap if not HTML looking
        html_body = llm_text
        if "<html" not in llm_text.lower():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            html_body = f"""<html><body>
<h1>Daily Web Intel - {today}</h1>
{llm_text}
</body></html>"""

        print("=== SES SECTION ===")
        sender = ses_cfg.get("sender")
        recipient = ses_cfg.get("recipient")
        subject = ses_cfg.get("subject", "Daily Web Intel")

        print(f"Sender: {sender}")
        print(f"Recipient: {recipient}")
        print(f"Subject: {subject}")

        if not sender or not recipient:
            print("ERROR: SES sender or recipient missing")
            return {"error": "SES sender or recipient missing"}

        ses_region = os.getenv("SES_REGION")  # optional
        print(f"SES region: {ses_region}")
        ses = _client("ses", region=ses_region)
        print("SES client created successfully")

        print("About to send email via SES...")
        ses_response = ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"}
                }
            }
        )
        print(f"SES send_email response: {ses_response}")

        result = {
            "status": "sent",
            "recipient": recipient,
            "subject": subject,
            "model": model_id,
            "message_id": ses_response.get("MessageId")
        }
        print(f"Final result: {result}")
        return result

    except Exception as e:
        print(f"ERROR in handler: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise e