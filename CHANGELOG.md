# Changelog

All notable, unreleased changes to this project will be documented in this file. For the released changes, please visit the [Releases](https://github.com/saleor/saleor/releases) page.

# 3.24.0 [Unreleased]

### Breaking changes

### GraphQL API

### Webhooks

Introduce a new mechanism for async webhook processing, providing fair resource distribution between apps and controlled concurrency.
Concept:

- Do not trigger send_webhook_request_async celery task immediately after EventDelivery is created.
- Use the celery beat scheduler to trigger the webhook sending whenever pending deliveries exist.
- Group deliveries by app ID
- Provide a DB-based mutex to ensure that only one celery worker at a time can process deliveries for one app.
- Use a controlled number of threads to process webhooks concurrently.
- In case of concurrency=1, always deliver webhooks in chronological order, including retries caused by https errors or timeouts.
- Keep the legacy solution available for backwards compatibility.
- Use the environment variable setting as a feature flag to switch between new and legacy webhook processing.

### Other changes

#### Search improvements

### Deprecations
