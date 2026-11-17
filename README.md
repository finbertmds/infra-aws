# AWS infrastructure settings

This repository groups AWS configuration by purpose. Each directory contains its own setup instructions, configuration, scripts, and checks.

| Directory | Purpose |
| --- | --- |
| [`budgets/`](budgets/README.md) | AWS Budgets cost alerts, IAM policies, and deployment workflow |

To work with AWS Budgets, start in its directory and follow the [Budgets guide](budgets/README.md):

```sh
cd budgets
```

Add future AWS settings in separate directories alongside `budgets/`.
