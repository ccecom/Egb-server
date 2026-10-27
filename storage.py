import os
import boto3
import uuid
from fastapi import UploadFile, HTTPException

# Initialize the S3 client using environment variables
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
    region_name=os.getenv('S3_REGION'),
    endpoint_url=os.getenv('S3_ENDPOINT') # Optional: Used for Cloudflare R2 or DO Spaces
)

BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
BUCKET_URL = os.getenv('S3_PUBLIC_URL') # e.g., https://your-bucket-url.com

async def upload_file_to_cloud(file: UploadFile, folder: str) -> str:
    """
    Uploads a FastAPI file to an S3-compatible bucket and returns the public URL.
    """
    try:
        # 1. Generate a unique filename to prevent overwriting
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"{folder}/{uuid.uuid4().hex}.{file_extension}"

        # 2. Read the file into memory
        file_contents = await file.read()

        # 3. Upload to the cloud bucket
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=unique_filename,
            Body=file_contents,
            ContentType=file.content_type
        )

        # 4. Return the permanent, public URL for your database
        return f"{BUCKET_URL}/{unique_filename}"

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloud upload failed: {str(e)}")
