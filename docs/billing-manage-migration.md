# Migrating to the Unified Billing Endpoint

## Overview

The new `/api/v1/billing/manage` endpoint simplifies billing integration by automatically determining whether a user needs checkout (to subscribe) or the customer portal (to manage existing subscription).

## Why Migrate?

### Before (Two Endpoints)
- Frontend must track user subscription state
- Frontend decides which endpoint to call (`/billing/checkout` or `/billing/portal`)
- Logic duplication between frontend and backend
- Race conditions possible if subscription state changes

### After (Single Endpoint)
- Backend determines the correct flow
- Frontend makes one call regardless of subscription state
- Single source of truth for subscription logic
- Simpler frontend code

## API Changes

### Request

**Endpoint:** `POST /api/v1/billing/manage`

**Required Fields:**
- `return_url` - Where to redirect after portal session (always required)
- `success_url` - Where to redirect after successful checkout (required for free users)
- `cancel_url` - Where to redirect if checkout is canceled (required for free users)

**Recommendation:** Always send all three URLs. The backend will use whichever ones are needed.

### Response

The response now includes a `type` field indicating which URL was returned:

| Field | Description |
|-------|-------------|
| `type` | Either `"checkout"` or `"portal"` |
| `url` | The Stripe URL to redirect to |
| `message` | Human-readable description |

### Response Scenarios

**Free User (no subscription):**
- `type`: `"checkout"`
- `url`: Stripe Checkout URL
- User will see plan selection and payment form

**Subscribed User (active or past_due):**
- `type`: `"portal"`
- `url`: Stripe Customer Portal URL
- User can manage subscription, update payment method, cancel, etc.

## Migration Steps

1. **Update API call** - Replace calls to `/billing/checkout` or `/billing/portal` with a single call to `/billing/manage`

2. **Update request body** - Send all three URLs (`return_url`, `success_url`, `cancel_url`) in every request

3. **Update response handling** - Read the `url` field from response (previously `checkout_url` or `portal_url`)

4. **Optional: Use `type` field** - If you want to show different UI or messaging based on whether user is subscribing vs managing, check the `type` field

5. **Remove subscription state checks** - You no longer need to check subscription status before deciding which endpoint to call

## Deprecation Notice

The old endpoints remain functional:
- `POST /api/v1/billing/checkout` - Still works
- `POST /api/v1/billing/portal` - Still works

However, new features will only be added to `/billing/manage`. Consider migrating when convenient.

## Error Handling

| Status Code | Meaning |
|-------------|---------|
| 400 | Missing `success_url` or `cancel_url` (only when user needs checkout) |
| 401 | Not authenticated |
| 502 | Stripe service error |
| 503 | Stripe not configured |

## Testing

1. **Test with free user** - Should receive `type: "checkout"`
2. **Test with subscribed user** - Should receive `type: "portal"`
3. **Verify redirects work** - Complete a test checkout/portal session
