# AWS Credentials Setup

Three methods, in order of recommendation for this project.

---

## Method 1 — Named profile with long-term keys (recommended for demos)

### 1. Install the AWS CLI

```bash
# macOS (Homebrew)
brew install awscli

# macOS (official pkg — no Homebrew needed)
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o /tmp/AWSCLIV2.pkg
sudo installer -pkg /tmp/AWSCLIV2.pkg -target /

# Verify
aws --version
```

### 2. Create an IAM user with programmatic access

1. AWS Console → **IAM** → Users → **Create user**
2. Name: e.g. `data-pipeline-poc`
3. Permissions: attach `AdministratorAccess` (for a demo) or the minimum policy below
4. **Security credentials** tab → **Create access key** → choose *CLI* use case
5. Copy the **Access key ID** and **Secret access key** — shown once only

<details>
<summary>Minimum IAM policy (least privilege for this project)</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "s3:*",               "Resource": "*" },
    { "Effect": "Allow", "Action": "lambda:*",            "Resource": "*" },
    { "Effect": "Allow", "Action": "glue:*",              "Resource": "*" },
    { "Effect": "Allow", "Action": "redshift-serverless:*","Resource": "*" },
    { "Effect": "Allow", "Action": "redshift-data:*",     "Resource": "*" },
    { "Effect": "Allow", "Action": "apigateway:*",        "Resource": "*" },
    { "Effect": "Allow", "Action": "iam:*",               "Resource": "*" },
    { "Effect": "Allow", "Action": "events:*",            "Resource": "*" },
    { "Effect": "Allow", "Action": "logs:*",              "Resource": "*" },
    { "Effect": "Allow", "Action": "sts:GetCallerIdentity","Resource": "*" }
  ]
}
```

</details>

### 3. Configure a named profile

```bash
aws configure --profile data-pipeline
```

You will be prompted for four values:

```
AWS Access Key ID [None]:     AKIAxxxxxxxxxxxxxxxxxx
AWS Secret Access Key [None]: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Default region name [None]:   eu-west-3
Default output format [None]: json
```

This writes two files:

**`~/.aws/credentials`**
```ini
[data-pipeline]
aws_access_key_id     = AKIAxxxxxxxxxxxxxxxxxx
aws_secret_access_key = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**`~/.aws/config`**
```ini
[profile data-pipeline]
region = eu-west-3
output = json
```

### 4. Set the profile in `.env`

```bash
# in your .env (copied from .env.example):
AWS_PROFILE=data-pipeline
```

### 5. Verify

```bash
source .env
aws sts get-caller-identity
```

Expected output:
```json
{
    "UserId": "AIDAxxx",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/data-pipeline-demo"
}
```

---

## Method 2 — AWS SSO / IAM Identity Center

Use this if your organisation manages access via AWS SSO (the modern approach —
no long-term keys, credentials auto-refresh).

### 1. Configure SSO once

```bash
aws configure sso --profile data-pipeline
```

You will be prompted for:

```
SSO session name: data-pipeline-session
SSO start URL:    https://my-org.awsapps.com/start     # from your IT/admin
SSO region:       eu-west-3                             # SSO control plane region
```

A browser window opens for login. After login, choose your account and role.

This writes to **`~/.aws/config`**:

```ini
[profile data-pipeline]
sso_session      = data-pipeline-session
sso_account_id   = 123456789012
sso_role_name    = AdministratorAccess
region           = eu-west-3
output           = json

[sso-session data-pipeline-session]
sso_start_url    = https://my-org.awsapps.com/start
sso_region       = eu-west-3
sso_registration_scopes = sso:account:access
```

### 2. Login (repeat when the 8-hour session expires)

```bash
aws sso login --profile data-pipeline
```

### 3. Set the profile in `.env`

```bash
AWS_PROFILE=data-pipeline
```

### 4. Verify

```bash
source .env
aws sts get-caller-identity --profile data-pipeline
```

---

## Method 3 — Environment variables directly (CI / quick test)

Suitable for CI pipelines or a one-off test. Not recommended for day-to-day
use because keys are visible in shell history.

```bash
export AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxxxx
export AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export AWS_DEFAULT_REGION=eu-west-3
# export AWS_SESSION_TOKEN=...    # required for assumed roles / SSO tokens
```

Or put them in your `.env` (gitignored) and `source .env`.

---

## Checking what credentials are active

```bash
# Which identity will be used?
aws sts get-caller-identity

# Which profile/source is boto3 picking up?
aws configure list

# List all configured profiles
aws configure list-profiles
```

---

## Credential precedence (how AWS CLI / boto3 resolves them)

When you run any AWS command, credentials are looked up in this order —
**first match wins**:

| Priority | Source |
|---|---|
| 1 | Environment variables (`AWS_ACCESS_KEY_ID`, etc.) |
| 2 | `AWS_PROFILE` env var → `~/.aws/credentials` + `~/.aws/config` |
| 3 | `~/.aws/credentials` `[default]` profile |
| 4 | `~/.aws/config` `[default]` profile |
| 5 | Container credentials (ECS task role) |
| 6 | EC2 instance metadata (instance profile) |

For this project the recommended setup is:
- **`.env`** sets `AWS_PROFILE=data-pipeline` (Method 1 or 2)
- **`~/.aws/credentials`** / **`~/.aws/config`** hold the actual keys
- Tests use `monkeypatch.setenv` (unit) or `.env.localstack` (integration) — no real credentials needed

---

## Multiple accounts / regions

Add extra profiles and switch between them in `.env`:

```ini
# ~/.aws/credentials
[data-pipeline]
aws_access_key_id     = AKIAxxxxxxxxxxxxxxxxxx
aws_secret_access_key = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

[data-pipeline-prod]
aws_access_key_id     = AKIAyyyyyyyyyyyyyyyyyy
aws_secret_access_key = yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
```

```bash
# ~/.aws/config
[profile data-pipeline]
region = eu-west-3

[profile data-pipeline-prod]
region = eu-west-1
```

Switch profile without editing `.env`:
```bash
AWS_PROFILE=data-pipeline-prod terraform plan
```

---

## Security checklist

- [ ] Never commit `~/.aws/credentials` or `.env` to Git (both are gitignored)
- [ ] Rotate long-term keys every 90 days (IAM → Security credentials → Access keys)
- [ ] Prefer SSO/IAM Identity Center over long-term keys for team environments
- [ ] For CI, use GitHub Actions OIDC (no stored secrets) rather than `AWS_ACCESS_KEY_ID` secrets — see [Configuring OpenID Connect in Amazon Web Services](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [ ] Scope the IAM policy to only the services this project needs (see the minimum policy above)
