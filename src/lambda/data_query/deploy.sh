#!/bin/bash
# Deploy data_query Lambda
# Run from project root: bash src/lambda/data_query/deploy.sh

set -e

FUNCTION_NAME="data_query"
LAMBDA_DIR="src/lambda/data_query"
ZIP_FILE="data_query.zip"
REGION="eu-west-1"
# Replace YOUR_ACCOUNT_ID with your AWS account ID
ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT_ID:role/techdocs-lambda-role"

# Load env for RDS creds — set -a auto-exports all vars so Python subprocess sees them
set -a
source .env
set +a

echo "=== Installing psycopg2-binary into Lambda package ==="
pip install psycopg2-binary \
    --target "$LAMBDA_DIR" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --quiet

echo "=== Zipping package ==="
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
        --timeout 30 \
        --memory-size 128 \
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
      'RDS_HOST': os.environ['RDS_HOST'],
      'RDS_DB': os.environ['RDS_DB'],
      'RDS_USER': os.environ['RDS_USER'],
      'RDS_PASSWORD': os.environ['RDS_PASSWORD']
    }
  }
}))
")
aws lambda update-function-configuration \
    --cli-input-json "$ENV_JSON" \
    --region "$REGION"

echo "=== Done: $FUNCTION_NAME deployed ==="
