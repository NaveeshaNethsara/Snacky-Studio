"""Create the private S3 bucket before APIs/workers start; retry bounded startup."""
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError


def main():
    client = boto3.client('s3', endpoint_url=os.environ['SNACKY_S3_ENDPOINT'],
                          region_name=os.getenv('SNACKY_S3_REGION', 'us-east-1'),
                          config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                        connect_timeout=3, read_timeout=5, retries={'max_attempts': 1}))
    bucket = os.getenv('SNACKY_S3_BUCKET', 'snacky-media')
    for attempt in range(30):
        try:
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError as error:
                if error.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                    raise
                options = {'Bucket': bucket}
                region = os.getenv('SNACKY_S3_REGION', 'us-east-1')
                if region != 'us-east-1':
                    options['CreateBucketConfiguration'] = {'LocationConstraint': region}
                client.create_bucket(**options)
            print('Private media bucket is ready.')
            return
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode'] < 500:
                raise
        except (EndpointConnectionError, ConnectionClosedError):
            pass
        if attempt < 29:
            time.sleep(2)
    raise SystemExit('The object store did not become ready. Check its container logs.')


if __name__ == '__main__':
    main()
