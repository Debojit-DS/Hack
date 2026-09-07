import json
from datetime import timedelta
from minio import Minio
from app.config import settings

minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ROOT_USER,
    secret_key=settings.MINIO_ROOT_PASSWORD,
    secure=settings.MINIO_USE_SSL,
)

def init_minio_bucket():
    bucket_name = settings.MINIO_BUCKET
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }
        minio_client.set_bucket_policy(bucket_name, json.dumps(policy))

def generate_presigned_upload_url(object_key: str):
    upload_url = minio_client.presigned_put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_key,
        expires=timedelta(minutes=15),
    )
    public_url = f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}/{object_key}"
    return upload_url, public_url