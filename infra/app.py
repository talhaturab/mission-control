"""Entry point: `cdk` runs this file and every stack it creates becomes a CloudFormation template."""

import os

from aws_cdk import App, Environment

from stacks.mission_control import MissionControlStack

app = App()
MissionControlStack(
    app,
    "MissionControl",
    env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="eu-west-2"),
)
app.synth()
