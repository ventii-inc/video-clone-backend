# Billing API Documentation

Base URL: `/api/v1/billing`

All endpoints (except webhooks) require Firebase authentication via `Authorization: Bearer <token>` header.

---

## Endpoints Overview

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/subscription` | GET | Yes | Get current subscription & payment method |
| `/checkout` | POST | Yes | Create Stripe checkout session |
| `/portal` | POST | Yes | Create Stripe customer portal session |
| `/invoices` | GET | Yes | Get payment history |
| `/prices` | GET | No | Get pricing info (public) |
| `/webhooks/stripe` | POST | No | Stripe webhook (internal) |

---

## 1. Get Current Subscription

Returns user's subscription status and default payment method.

**Request**
```
GET /api/v1/billing/subscription
Authorization: Bearer <firebase_token>
```

**Response (200 OK)**
```json
{
  "subscription": {
    "plan_type": "standard",
    "status": "active",
    "monthly_minutes_limit": 100,
    "current_period_start": "2025-01-01T00:00:00",
    "current_period_end": "2025-02-01T00:00:00",
    "cancel_at_period_end": false
  },
  "payment_method": {
    "type": "card",
    "brand": "visa",
    "last4": "4242",
    "exp_month": 12,
    "exp_year": 2025
  }
}
```

**Response (No subscription)**
```json
{
  "subscription": null,
  "payment_method": null
}
```

**Fields**
| Field | Type | Description |
|-------|------|-------------|
| `plan_type` | string | `free` or `standard` |
| `status` | string | `active`, `canceled`, `past_due`, `trialing` |
| `monthly_minutes_limit` | int | Minutes included per month (0 for free, 100 for standard) |
| `cancel_at_period_end` | bool | True if subscription will cancel at period end |
| `payment_method` | object/null | Default card info, null if none |

---

## 2. Create Checkout Session (Subscribe)

Creates a Stripe Checkout session for subscription. Redirect user to the returned URL.

**Request**
```
POST /api/v1/billing/checkout
Authorization: Bearer <firebase_token>
Content-Type: application/json

{
  "success_url": "https://yourapp.com/billing?success=true",
  "cancel_url": "https://yourapp.com/billing?canceled=true"
}
```

**Response (200 OK)**
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_..."
}
```

**Errors**
| Status | Code | Description |
|--------|------|-------------|
| 401 | Unauthorized | Invalid or missing Firebase token |
| 502 | Bad Gateway | Stripe API error |
| 503 | Service Unavailable | Stripe not configured |

**Flow**
1. Call this endpoint
2. Redirect user to `checkout_url`
3. User completes payment on Stripe
4. Stripe redirects to `success_url` or `cancel_url`
5. Webhook updates subscription in backend

---

## 3. Create Customer Portal Session

Creates a Stripe Customer Portal session for managing subscription (update card, cancel, view invoices).

**Request**
```
POST /api/v1/billing/portal
Authorization: Bearer <firebase_token>
Content-Type: application/json

{
  "return_url": "https://yourapp.com/billing"
}
```

**Response (200 OK)**
```json
{
  "portal_url": "https://billing.stripe.com/p/session/..."
}
```

**Errors**
| Status | Code | Description |
|--------|------|-------------|
| 401 | Unauthorized | Invalid or missing Firebase token |
| 502 | Bad Gateway | Stripe API error |
| 503 | Service Unavailable | Stripe not configured |

---

## 4. Get Payment History (Invoices)

Returns list of invoices from Stripe with download links.

**Request**
```
GET /api/v1/billing/invoices?page=1&limit=10
Authorization: Bearer <firebase_token>
```

**Query Parameters**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `limit` | int | 10 | Items per page (max 100) |

**Response (200 OK)**
```json
{
  "invoices": [
    {
      "id": "in_1abc123",
      "amount": 2980,
      "currency": "jpy",
      "status": "paid",
      "created_at": "2025-01-01T00:00:00",
      "invoice_url": "https://invoice.stripe.com/i/...",
      "invoice_pdf": "https://pay.stripe.com/invoice/.../pdf"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 5,
    "total_pages": 1
  }
}
```

**Invoice Fields**
| Field | Type | Description |
|-------|------|-------------|
| `invoice_url` | string | Stripe-hosted invoice page |
| `invoice_pdf` | string | Direct PDF download link |
| `status` | string | `draft`, `open`, `paid`, `void`, `uncollectible` |

---

## 5. Get Pricing (Public)

Returns current pricing information. No authentication required.

**Request**
```
GET /api/v1/billing/prices
```

**Response (200 OK)**
```json
{
  "subscription": {
    "name": "Standard Plan",
    "price_jpy": 2980,
    "minutes_per_month": 100,
    "billing_period": "monthly"
  },
  "minutes_pack": {
    "name": "Additional Minutes",
    "price_jpy": 1000,
    "minutes": 20
  }
}
```

---

## Common Error Responses

**401 Unauthorized**
```json
{
  "detail": "Invalid authentication credentials"
}
```

**502 Bad Gateway**
```json
{
  "detail": "Payment service error. Please try again."
}
```

**503 Service Unavailable**
```json
{
  "detail": "STRIPE_SECRET_KEY not configured"
}
```

---

## Frontend Integration Flow

### Subscribe Flow
1. User clicks "Subscribe" button
2. Call `POST /billing/checkout` with success/cancel URLs
3. Redirect to `checkout_url`
4. After payment, user returns to `success_url`
5. Fetch `GET /billing/subscription` to confirm status

### Manage Subscription Flow
1. User clicks "Manage Subscription" button
2. Call `POST /billing/portal` with return URL
3. Redirect to `portal_url`
4. User updates card / cancels / views invoices
5. User returns to `return_url`

### Display Subscription Status
1. Call `GET /billing/subscription` on page load
2. If `subscription` is null → show "Subscribe" button
3. If `plan_type` is "free" → show "Upgrade" button
4. If `plan_type` is "standard" → show subscription details & "Manage" button
5. If `payment_method` exists → display card info (brand + last4)

---

## Test Cards (Stripe Test Mode)

| Card Number | Result |
|-------------|--------|
| 4242 4242 4242 4242 | Success |
| 4000 0000 0000 3220 | 3D Secure required |
| 4000 0000 0000 9995 | Decline (insufficient funds) |

Use any future expiry date and any 3-digit CVC.
