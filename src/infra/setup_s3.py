"""
Run this script once to verify the S3 bucket exists and create the raw/ prefix.
Usage: python -m src.infra.setup_s3
"""
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

BUCKET = os.environ["S3_BUCKET"]
REGION = os.environ.get("AWS_REGION", "eu-west-1")


def setup():
    s3 = boto3.client("s3", region_name=REGION)

    # Check bucket exists
    s3.head_bucket(Bucket=BUCKET)
    print(f"Bucket {BUCKET} confirmed.")

    # Create raw/ prefix placeholder
    s3.put_object(Bucket=BUCKET, Key="raw/.gitkeep", Body=b"")
    print("Created raw/ prefix in bucket.")
    print("S3 setup complete. Upload PDFs to s3://{BUCKET}/raw/")


if __name__ == "__main__":
    setup()
