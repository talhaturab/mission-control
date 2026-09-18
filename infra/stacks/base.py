"""BaseStack: deployed once, by hand. What the pipeline needs before it can run.

  cdk deploy Base --profile talhasandbox

1. the ECR repository the pipeline pushes images into
2. an IAM role GitHub Actions may assume, with no password or access key (OIDC)
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_HOST = "token.actions.githubusercontent.com"
GITHUB_REPO = "talhaturab/mission-control"


class BaseStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        self.repository = ecr.Repository(
            self,
            "Repository",
            repository_name="mission-control",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # An account can hold one OIDC provider for GitHub, and this account already has one,
        # so we refer to it. In an empty account: iam.OidcProviderNative(self, "GitHub",
        # url=f"https://{GITHUB_HOST}", client_ids=["sts.amazonaws.com"]).
        provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self, "GitHub", f"arn:aws:iam::{self.account}:oidc-provider/{GITHUB_HOST}"
        )

        # GitHub signs a token naming the repository and branch. Newer repositories get the
        # "immutable" form with numeric ids after the owner and name; we accept both.
        owner, name = GITHUB_REPO.split("/")
        subjects = [
            f"repo:{owner}/{name}:ref:refs/heads/main",
            f"repo:{owner}@*/{name}@*:ref:refs/heads/main",
        ]
        deploy_role = iam.Role(
            self,
            "DeployRole",
            role_name="mission-control-github-deploy",
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {f"{GITHUB_HOST}:aud": "sts.amazonaws.com"},
                    "StringLike": {f"{GITHUB_HOST}:sub": subjects},
                },
            ),
        )
        # What the pipeline may do: push to this one repository, and switch into the roles
        # that `cdk bootstrap` made, which is how `cdk deploy` does its work.
        self.repository.grant_pull_push(deploy_role)
        deploy_role.add_to_policy(
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"])
        )
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"], resources=[f"arn:aws:iam::{self.account}:role/cdk-*"]
            )
        )

        CfnOutput(self, "DeployRoleArn", value=deploy_role.role_arn)
        CfnOutput(self, "RepositoryUri", value=self.repository.repository_uri)
