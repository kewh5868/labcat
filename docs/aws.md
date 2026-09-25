# Optional AWS integration

The workspace runs locally by default. The setup window offers optional AWS
model compute, alongside optional research data APIs. Selecting another supported
model account satisfies setup without an AWS account. An existing AWS profile can supply a
read-only identity check and optional Bedrock model planning. Configuring it does
not move the application to AWS or create resources. AWS authentication stays in
the AWS CLI/SSO flow; the app remembers a profile reference, not an AWS password.

## Configure and check an existing account

The Docker application does not read host AWS profiles, credentials, SSO caches,
or other host folders. Do not add bind mounts for `~/.aws`, a home directory,
repository, lab data, the Docker socket, or Downloads. Model credentials must be
provided through the application's connection controls or a site-managed
container credential mechanism.

The current image includes Boto3 but does not include an AWS CLI sign-in wizard.
A site administrator can provision a dedicated named AWS profile within the
container environment using their approved credential mechanism. Container SSO
and IAM configuration require site validation. The profile name and region in
Connections refer to that container configuration; choosing them does not copy a
host profile or initiate AWS sign-in. Provider-owned AWS SSO setup is described
in the [AWS CLI SSO guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
and [Boto3 credentials guide](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).

In **Connections**, choose AWS Bedrock and use the profile and region dropdowns.
The setup guide links to the official SSO instructions. Refreshing profile choices
reads names available to this installation; it does not authenticate or reveal
credentials. Load available models explicitly queries Bedrock's text-model
catalog. An empty catalog or failed lookup does not trigger inference or create
resources; model access must still be checked with the site's permissions.

For required model setup, select a Bedrock model, enable hosted-context consent,
and run the account readiness check. This verifies the selected profile's
identity and its regional model catalog entry. It does not prove inference
authorization or enable a model subscription. AWS connection details can also be
configured later; skipping AWS keeps the application and workspace local.

`aws-check` uses Boto3's selected session to call STS `GetCallerIdentity` and
report authenticated status. It intentionally omits the account ID, principal
ARN and other identity details from output. It makes no model request and
creates no compute resources. STS is offered at no additional service charge.
The result establishes identity only: this operation requires no IAM permission,
so success proves neither Bedrock access nor deployment permissions.
[GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html),
[STS service cost](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html)

## Inference versus hosting

**Implemented optional Bedrock planning:** keep the application local and send bounded model
requests to a configured Bedrock model. Select a model and region, grant only
the required inference permissions, and complete applicable model-access
prerequisites. Some third-party models require marketplace enablement and
provider-specific steps. A first invocation can start model subscription
setup; it must not be used as a harmless connectivity test. Signing in locally
does not authorize every model.
[Inference permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference.html),
[Model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)

**Future ECS Fargate hosting:** run the application container as an ECS task or service
when a shared cloud deployment is useful. Reuse the Docker image and configuration
contract, with an image build matching the target CPU architecture. An ECS task
definition supplies runtime settings and resource allocation. This requires a
deployment plan for networking, authenticated access, logs and teardown; Docker
portability alone does not supply those pieces. Fargate is application hosting,
not an automatic source of LLM inference.
[Fargate application deployment](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/getting-started-fargate.html)

## Credentials and operating cost

Use temporary SSO credentials for local development. In ECS, use a narrowly
scoped **task role** for application API calls and a separate **task execution
role** for image pulls, log delivery and configured secret injection. Never bake
personal profiles, SSO caches or keys into images or Git. Keep provider keys in a
secrets manager and account identifiers out of public interview screenshots.
[ECS role responsibilities](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-iam-roles.html)

Bedrock inference and Fargate resources incur separate charges; networking,
logging and storage can add costs. Before deployment, estimate the chosen
region/model, set workload and token limits, and define teardown steps. No free
cloud-compute allowance is assumed. [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/),
[Fargate pricing](https://aws.amazon.com/fargate/pricing/)

Documentation checked September 9, 2026. AWS identity is deployment metadata,
never a source of materials-science evidence.

Report exports are downloaded by the desktop application or browser after the
user chooses an export. They do not expose the Downloads directory to Docker or
Goose. Goose executes inside Docker with the application's restricted research
tools; it receives only the selected provider credentials for that run, never
access to host credential stores. No cloud deployment is automated here.
