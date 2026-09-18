"""Entry point: `cdk` runs this file and every stack it creates becomes a CloudFormation template."""

import os

from aws_cdk import App, Environment

from stacks.base import BaseStack
from stacks.mission_control import MissionControlStack

app = App()
env = Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="eu-west-2")
BaseStack(app, "Base", env=env)  # once, by hand
MissionControlStack(app, "MissionControl", env=env)  # by the pipeline, every merge
app.synth()
