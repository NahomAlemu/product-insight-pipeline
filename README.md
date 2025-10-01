## Product Insight Pipeline (Serverless SEC Data Analyzer)

A fully serverless AWS pipeline that ingests **public company financial filings** (via SEC EDGAR API), enriches them with key KPIs, and generates **sales-ready ROI briefs** using **Amazon Bedrock (Claude 3 Sonnet)**. The pipeline runs on a daily schedule and automatically emails the results to a designated recipient.

---

### Features
- **Automated Ingestion**  
  Fetches company financials and submissions data from SEC EDGAR daily.

- **Feature Engineering**  
  Extracts KPIs like:
  - Latest annual revenue
  - YoY revenue growth %
  - Sales & Marketing spend as % of revenue
  - Industry classification

- **AI Analysis**  
  Uses Claude 3 Sonnet (Amazon Bedrock) to generate:
  - JSON insights (pain points, value hypothesis, next best action)  
  - A clean HTML sales brief

- **Automated Distribution**  
  Stores JSON + HTML in S3 and emails the formatted brief via Amazon SES.


**Core AWS Services**
- **EventBridge** → daily trigger
- **Step Functions** → orchestrator (parallel + sequential steps)
- **Lambda (Python)** → compute units:
  - `fetch_edgar_data` → call SEC API + store in S3
  - `build_features` → extract financial KPIs
  - `generate_roi_brief` → Bedrock analysis + SES email
- **Bedrock** → LLM analysis with Claude 3 Sonnet
- **S3** → store intermediate + final artifacts
- **SES** → deliver ROI briefs
- **Secrets Manager** → (if using external APIs or sensitive keys)
- **IAM** → least-privilege role for Lambdas + Step Functions


### Prerequisites
- AWS Account with Bedrock, SES, Step Functions, and Lambda access
- AWS CLI configured
- Verified SES sender email (and recipient if sandboxed)
- Python 3+  
- (Optional) EDGAR data is public, so no API key required


### Deployment
1. Clone the repo:
   ```bash
    git clone https://github.com/NahomAlemu/product-insight-pipeline.git 
    cd product-insight-pipeline
    ```
2. Deploy with SAM:
   ```bash 
   sam build
   sam deploy --guided 
   ```

### Testing

Run a manual execution with simulation enabled (no Bedrock call):

``` 
aws stepfunctions start-execution \
  --state-machine-arn <YOUR-STATE-MACHINE-ARN> \
  --name "smoke-$(date +%s)" \
  --input '{
    "accounts": [{"name":"Starbucks","cik":"0000829224"}],
    "bedrock": {"region":"us-west-2","simulate": true},
    "ses": {"sender":"you@domain.com","recipient":"you@domain.com"}
  }' 

```
