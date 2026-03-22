#!/bin/bash
# Deploy api_gateway Lambda
# Run from project root: bash src/lambda/api_gateway/deploy.sh

set -e

FUNCTION_NAME="api_gateway"
LAMBDA_DIR="src/lambda/api_gateway"
ZIP_FILE="api_gateway.zip"
REGION="eu-west-1"
# Replace YOUR_ACCOUNT_ID with your AWS account ID
ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT_ID:role/techdocs-lambda-role"

# Load env — set -a exports all vars to Python subprocess
set -a
source .env
set +a

echo "=== Zipping package ==="
# No extra dependencies — only boto3 (provided by Lambda runtime)
cd "$LAMBDA_DIR"
zip -r "../../../$ZIP_FILE" . -x "*.pyc" -x "*/__pycache__/*" -x "deploy.sh" -x "test_local.py"
cd ../../..

echo "=== Deploying to Lambda (create or update) ==="
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" > /dev/null 2>&1; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION"
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler handler.handler \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 120 \
        --memory-size 256 \
        --region "$REGION" \
        --vpc-config "SubnetIds=YOUR_SUBNET_ID_A,YOUR_SUBNET_ID_B,SecurityGroupIds=YOUR_LAMBDA_SG_ID"

    echo "=== Waiting for function to become active ==="
    aws lambda wait function-active \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION"
fi

echo "=== Setting environment variables ==="
ENV_JSON=$(python3 -c "
import os, json
print(json.dumps({
  'FunctionName': '$FUNCTION_NAME',
  'Environment': {
    'Variables': {
      'SUPERVISOR_AGENT_ID': os.environ['SUPERVISOR_AGENT_ID'],
      'SUPERVISOR_AGENT_ALIAS_ID': os.environ['SUPERVISOR_AGENT_ALIAS_ID']
    }
  }
}))
")
aws lambda update-function-configuration \
    --cli-input-json "$ENV_JSON" \
    --region "$REGION"

echo "=== Done: $FUNCTION_NAME deployed ==="
