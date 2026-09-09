# voipms-mcp

VOIP.ms Integration MCP for the MSPbots Agent Platform.

Status: **empty scaffold** — created 2026-09-09 for [PRD-18607](https://app.clickup.com/t/86e36377t).
Design has not been done yet; nothing here is implemented.

## Why this repo exists

The manual workflow it replaces: an ops/support user finds a user's VOIP.ms
sub-account and redirects their voicemail to a requested target. The documented
SOP has 12 steps, but only 2 of them are real actions — the rest is portal
navigation, which is not worth modelling as tools.

## Planned tool surface (MVP)

| tool | what it does |
|---|---|
| `voipms.find_subaccount` | locate a user's sub-account |
| `voipms.get_subaccount` | read the sub-account's full current configuration |
| `voipms.list_voicemail_boxes` | list voicemail boxes, so a destination can be validated before it is used |
| `voipms.set_voicemail_redirect` | update the voicemail redirect |

## The constraint that must not be lost

**`set_voicemail_redirect` must be read-modify-write. Never a single-field blind write.**

The vendor's `setSubAccount` behaves like a *set*, not a *patch*: fields that are
absent from the request are reset to their defaults. Sending only
`internal_voicemail` would therefore silently wipe unrelated settings on a live
customer account. The implementation must read the full sub-account, change only
the intended field, write the whole object back, and return a before/after
comparison.

## Known prerequisites (not yet confirmed by the customer, as of PRD-18607)

- VOIP.ms API enablement on the account
- the execution account and its API password
- a stable platform egress IP, allowlisted on the VOIP.ms side (the API
  authenticates by IP allowlist)

Without these the implementation cannot be tested against anything real.

## Registration

New vendor MCPs are registered in `mcp-service-gateway`'s `vendor/registry.yaml`
(`name` / `repo_url` / `credential_fields`), following `bvoip-mcp`,
`oitvoip-mcp`, `chargebee-mcp` and `bamboohr-mcp`. That entry does not exist yet.

Note: `bvoip` (1Stream) and `oitvoip` (NetSapiens PBX) are already registered and
are **different vendors** — their names merely contain the substring "voip".
