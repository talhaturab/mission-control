"""One stack, everything Mission Control needs on AWS.

    cdk deploy --profile talhasandbox

Four kinds of process become three kinds of ECS thing:
  web     an ECS Express service: Fargate task + load balancer + HTTPS URL
  worker  a plain ECS service on Fargate, 2 tasks, autoscaled on CPU
  ticker  a scheduled Fargate task, every 5 minutes, runs once and exits
The image is built from this repository at deploy time and pushed to ECR by CDK itself.
Step 5 replaces that with the image the pipeline built.
"""

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

# Created by hand, once. Never in git:
#   aws secretsmanager create-secret --name mission-control/openrouter --secret-string sk-or-...
SECRET_NAME = "mission-control/openrouter"


class MissionControlStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # --- network: two public subnets, no NAT gateway ($35/month saved) ------------------
        vpc = ec2.Vpc(
            self,
            "Vpc",
            availability_zones=["eu-west-2a", "eu-west-2b"],
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)
            ],
        )
        public = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)

        # --- the image: CDK builds the Dockerfile and pushes it to ECR during deploy --------
        image = ecr_assets.DockerImageAsset(
            self, "Image", directory="..", platform=ecr_assets.Platform.LINUX_AMD64
        )

        # --- the secret, referenced by name; the value stays in Secrets Manager -------------
        openrouter = secretsmanager.Secret.from_secret_name_v2(self, "OpenRouter", SECRET_NAME)

        # --- roles ECS needs ------------------------------------------------------------------
        # Execution role: what ECS uses to START a task (pull the image, read the secret, write logs).
        execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        openrouter.grant_read(execution_role)
        image.repository.grant_pull(execution_role)
        # Infrastructure role: what Express Mode uses to BUILD the load balancer and certificate.
        infrastructure_role = iam.Role(
            self,
            "InfrastructureRole",
            assumed_by=iam.ServicePrincipal("ecs.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
                )
            ],
        )

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, cluster_name="mission-control")

        # --- web: Express Mode gives us the load balancer and the HTTPS URL ------------------
        web = ecs.CfnExpressGatewayService(
            self,
            "Web",
            service_name="mission-control-web",
            cluster=cluster.cluster_name,
            execution_role_arn=execution_role.role_arn,
            infrastructure_role_arn=infrastructure_role.role_arn,
            cpu="512",
            memory="1024",
            health_check_path="/health",
            primary_container=ecs.CfnExpressGatewayService.ExpressGatewayContainerProperty(
                image=image.image_uri,
                container_port=8000,
                environment=[
                    ecs.CfnExpressGatewayService.KeyValuePairProperty(name="TASK_NAME", value="aws")
                ],
                secrets=[
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="OPENROUTER_API_KEY", value_from=openrouter.secret_arn
                    )
                ],
            ),
            network_configuration=(
                ecs.CfnExpressGatewayService.ExpressGatewayServiceNetworkConfigurationProperty(
                    subnets=vpc.select_subnets(subnet_type=ec2.SubnetType.PUBLIC).subnet_ids
                )
            ),
            scaling_target=ecs.CfnExpressGatewayService.ExpressGatewayScalingTargetProperty(
                min_task_count=1, max_task_count=2
            ),
        )
        web.node.add_dependency(cluster)
        hub_url = f"https://{web.attr_endpoint}"

        # --- worker: a normal Fargate service, several copies, scaled on CPU -----------------
        worker_task = ecs.FargateTaskDefinition(
            self, "WorkerTask", cpu=256, memory_limit_mib=512, execution_role=execution_role
        )
        worker_task.add_container(
            "worker",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            command=["python", "-m", "app.worker"],
            environment={"HUB_URL": hub_url},
            secrets={"OPENROUTER_API_KEY": ecs.Secret.from_secrets_manager(openrouter)},
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="worker", log_retention=logs.RetentionDays.ONE_WEEK
            ),
        )
        worker = ecs.FargateService(
            self,
            "Worker",
            cluster=cluster,
            task_definition=worker_task,
            desired_count=2,
            assign_public_ip=True,  # no NAT: a public IP is how the task reaches ECR and the hub
            vpc_subnets=public,
            min_healthy_percent=0,  # a deploy may stop the old workers before starting new ones
            # If new tasks keep failing to start, stop the deploy and roll back to the old ones.
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        # The autoscaling policy: keep average CPU near 50%, between 1 and 4 workers.
        # Queue up count_primes jobs and watch the count climb; leave it idle and watch it fall.
        worker.auto_scale_task_count(min_capacity=1, max_capacity=4).scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=50,
            scale_out_cooldown=Duration.seconds(60),
            scale_in_cooldown=Duration.seconds(120),
        )

        # --- ticker: a task that runs once, on a schedule ----------------------------------------
        patterns.ScheduledFargateTask(
            self,
            "Ticker",
            cluster=cluster,
            schedule=appscaling.Schedule.rate(Duration.minutes(5)),
            subnet_selection=public,
            scheduled_fargate_task_image_options=patterns.ScheduledFargateTaskImageOptions(
                image=ecs.ContainerImage.from_docker_image_asset(image),
                command=["python", "-m", "app.ticker"],
                environment={"HUB_URL": hub_url, "TASK_NAME": "aws"},
                cpu=256,
                memory_limit_mib=512,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="ticker", log_retention=logs.RetentionDays.ONE_WEEK
                ),
            ),
        )

        CfnOutput(self, "DashboardUrl", value=hub_url)
