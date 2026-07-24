# ChainGuard API Versioning and Deprecation Policy

## Contract

ChainGuard versions its tenant-facing HTTP API in the URL: `/api/v1`,
`/api/v2`, and later major versions.  A major version is an independently
deployable compatibility contract.  Clients must send requests to one explicit
major-version prefix; ChainGuard does not negotiate business API versions with
an `Accept` header.

URL versioning makes the selected contract visible in logs, traces, proxy
rules, generated SDKs, and incident reports.  Header negotiation would require
every intermediary and support tool to preserve and interpret an extra
contract-selection header, while still leaving a single URL ambiguous.

## Adding v2 while v1 remains supported

1. Add a separate `/api/v2` router.  Do not mutate an existing v1 route's
   request or response contract to introduce a breaking change.
2. Keep the v1 route available and behaviorally stable throughout its published
   support window.  A v2 endpoint may initially share domain implementation
   with v1, but its route declaration and OpenAPI operation are independent.
3. Publish the v2 OpenAPI document, migration notes, examples, and client-SDK
   guidance before declaring any v1 endpoint deprecated.
4. Migrate first-party callers and named enterprise integrations, and monitor
   v1 traffic and error rates by route before removal.

The running example is `GET /api/v1/dashboard/top-risks`, whose compatible v2
successor is `GET /api/v2/dashboard/top-risks`.  Both routes are live.  The v1
operation is marked `deprecated: true` in OpenAPI and carries an
`x-chainguard-deprecation` extension containing its replacement and dates.

## Deprecation notice and grace period

Each deprecated operation has one source of truth in
`src/webapi/versioning.py`.  The response middleware applies the policy to the
exact HTTP method and path, including non-2xx responses, so an auth or business
error cannot hide a lifecycle warning.

The announcement must include:

- the deprecated method and path;
- the exact replacement and any request/response mapping;
- a migration guide and named technical owner;
- the deprecation effective date and UTC sunset date; and
- customer notification through release notes plus direct notice to registered
  enterprise integration contacts.

The minimum public grace period is **180 calendar days** from notice to sunset.
The clock begins only when the replacement, its OpenAPI contract, and migration
material are available.  A contract with high-volume enterprise integrations,
regulated workflows, or a customer-specific migration blocker receives a
longer published window (normally 12 months) rather than an exception to the
notice requirement.  Security or legal emergencies may require a shorter
window; the incident record must describe the risk, affected customers, and
mitigation.

At runtime, a deprecated endpoint sends:

- `Deprecation: @<unix-seconds>` — the RFC 9745 structured-field date on which
  the endpoint became deprecated;
- `Sunset: <HTTP-date>` — the earliest published removal time; and
- `Link: <replacement>; rel="successor-version"` — the direct replacement.

The headers warn without changing endpoint semantics.  They remain present
until the endpoint is actually removed.

## Breaking changes and removal

Breaking changes include deleting or renaming a field, changing its type or
meaning, making a formerly optional input required, altering pagination or
error semantics, changing authorization behavior, or weakening a documented
ordering/consistency guarantee.  They require a new major URL version.

Before removal, the API owner must verify that the sunset date has passed,
review route-level v1 traffic for at least 30 days, contact known customers
still using the endpoint, publish final release notes, and obtain release-owner
approval.  After removal, the former endpoint returns the normal 404 contract;
do not silently redirect unsafe methods or reinterpret a v1 payload as v2.

`Deprecation` follows [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html);
`Sunset` follows RFC 8594.  The date formats intentionally differ: the former
is a Structured Fields date and the latter is an HTTP-date.
