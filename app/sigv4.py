"""Sign HTTP requests with the AWS credentials of the process, the way the AWS CLI does.

The AgentCore Gateway accepts requests from an IAM identity. Our MCP client is httpx, which
knows nothing about AWS, so this small adapter signs each request before it leaves.
"""

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class SigV4(httpx.Auth):
    requires_request_body = True

    def __init__(self, service: str, region: str) -> None:
        self.service, self.region = service, region
        self.session = boto3.Session()

    def auth_flow(self, request: httpx.Request):
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
        credentials = self.session.get_credentials().get_frozen_credentials()
        SigV4Auth(credentials, self.service, self.region).add_auth(aws_request)
        request.headers.update(dict(aws_request.headers))
        yield request
