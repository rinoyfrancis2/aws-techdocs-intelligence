"""
setup_api_gateway.py
Wires AWS API Gateway REST API to the deployed api_gateway Lambda.

Creates:
  - REST API: techdocs-api
  - Resource: /query
  - Method: POST (Lambda Proxy integration)
  - Stage: prod
  - Lambda invoke permission

Run from project root:
    python src/infra/setup_api_gateway.py

After running, prints the invoke URL:
    POST https://{api-id}.execute-api.eu-west-1.amazonaws.com/prod/query
"""

import boto3
import json
import os

REGION = os.environ.get("AWS_REGION", "eu-west-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "YOUR_ACCOUNT_ID")  # set in .env
LAMBDA_FUNCTION_NAME = "api_gateway"
API_NAME = "techdocs-api"
STAGE_NAME = "prod"

apigw = boto3.client("apigateway", region_name=REGION)
lmb = boto3.client("lambda", region_name=REGION)


def get_lambda_arn() -> str:
    resp = lmb.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
    return resp["Configuration"]["FunctionArn"]


def find_existing_api(name: str) -> str | None:
    """Return the API id if an API with this name already exists, else None."""
    paginator = apigw.get_paginator("get_rest_apis")
    for page in paginator.paginate():
        for api in page["items"]:
            if api["name"] == name:
                return api["id"]
    return None


def create_rest_api() -> str:
    api_id = find_existing_api(API_NAME)
    if api_id:
        print(f"REST API '{API_NAME}' already exists: {api_id}")
        return api_id

    resp = apigw.create_rest_api(
        name=API_NAME,
        description="TechDocs Intelligence — multi-agent RAG query API",
        endpointConfiguration={"types": ["REGIONAL"]},
    )
    api_id = resp["id"]
    print(f"Created REST API '{API_NAME}': {api_id}")
    return api_id


def get_root_resource_id(api_id: str) -> str:
    resources = apigw.get_resources(restApiId=api_id)
    for r in resources["items"]:
        if r["path"] == "/":
            return r["id"]
    raise RuntimeError("Could not find root resource '/'")


def get_or_create_query_resource(api_id: str, root_id: str) -> str:
    resources = apigw.get_resources(restApiId=api_id)
    for r in resources["items"]:
        if r.get("pathPart") == "query":
            print(f"/query resource already exists: {r['id']}")
            return r["id"]

    resp = apigw.create_resource(
        restApiId=api_id,
        parentId=root_id,
        pathPart="query",
    )
    resource_id = resp["id"]
    print(f"Created /query resource: {resource_id}")
    return resource_id


def create_post_method(api_id: str, resource_id: str, lambda_arn: str):
    # Check if POST already exists
    try:
        apigw.get_method(restApiId=api_id, resourceId=resource_id, httpMethod="POST")
        print("POST method already exists on /query")
    except apigw.exceptions.NotFoundException:
        apigw.put_method(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            authorizationType="NONE",
        )
        print("Created POST method on /query")

    # Lambda proxy integration URI
    integration_uri = (
        f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions"
        f"/{lambda_arn}/invocations"
    )

    apigw.put_integration(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod="POST",
        type="AWS_PROXY",
        integrationHttpMethod="POST",
        uri=integration_uri,
    )
    print("Wired Lambda Proxy integration on POST /query")

    # 200 method response
    try:
        apigw.get_method_response(
            restApiId=api_id, resourceId=resource_id, httpMethod="POST", statusCode="200"
        )
    except apigw.exceptions.NotFoundException:
        apigw.put_method_response(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            statusCode="200",
            responseModels={"application/json": "Empty"},
        )


def add_lambda_permission(api_id: str, lambda_arn: str):
    source_arn = f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/POST/query"
    statement_id = "apigateway-techdocs-invoke"

    try:
        lmb.add_permission(
            FunctionName=LAMBDA_FUNCTION_NAME,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn,
        )
        print(f"Added Lambda invoke permission (statement: {statement_id})")
    except lmb.exceptions.ResourceConflictException:
        print(f"Lambda invoke permission already exists (statement: {statement_id})")


def deploy_to_stage(api_id: str) -> str:
    resp = apigw.create_deployment(
        restApiId=api_id,
        stageName=STAGE_NAME,
        description="Initial deployment — techdocs-api",
    )
    print(f"Deployed to stage '{STAGE_NAME}': deployment {resp['id']}")
    invoke_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/{STAGE_NAME}/query"
    return invoke_url


def main():
    print("=== Wiring API Gateway for TechDocs Intelligence ===\n")

    lambda_arn = get_lambda_arn()
    print(f"Lambda ARN: {lambda_arn}\n")

    api_id = create_rest_api()
    root_id = get_root_resource_id(api_id)
    resource_id = get_or_create_query_resource(api_id, root_id)
    create_post_method(api_id, resource_id, lambda_arn)
    add_lambda_permission(api_id, lambda_arn)
    invoke_url = deploy_to_stage(api_id)

    print(f"\n=== Done ===")
    print(f"\nInvoke URL:\n  POST {invoke_url}")
    print(f"\nTest with curl:")
    print(f"""  curl -X POST '{invoke_url}' \\
    -H 'Content-Type: application/json' \\
    -d '{{"query": "What does the nmap cheatsheet say about SYN scans?"}}'""")

    # Save the API ID and URL for reference
    output = {
        "api_id": api_id,
        "stage": STAGE_NAME,
        "invoke_url": invoke_url,
        "region": REGION,
    }
    with open("outputs/api_gateway_config.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nConfig saved to outputs/api_gateway_config.json")


if __name__ == "__main__":
    main()
