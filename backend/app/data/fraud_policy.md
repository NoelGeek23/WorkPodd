# Shopward Anti-Fraud & Refund Abuse Policy

Version 1.0 · Effective Date: January 15, 2026

## Purpose

The purpose of this policy is to identify potentially fraudulent refund requests while protecting legitimate customers. This policy supplements the Shopward Refund & Returns Policy and provides the fraud detection criteria used by customer support representatives, automated fraud engines, and AI agents.

A fraud risk assessment does not automatically deny a refund. It determines the level of review required before a refund decision is made.

## Fraud Risk Levels

Every refund request shall be assigned one of four fraud risk levels.

| Risk Level | Score | Action |
| --- | --- | --- |
| Low | 0–25 | Automatic Processing |
| Medium | 26–50 | Additional Verification |
| High | 51–75 | Manual Review |
| Critical | 76–100 | Refund Suspended Pending Investigation |

Where multiple high-risk indicators exist, the highest applicable risk level should be assigned.

## Customer Account Risk

The following account characteristics increase fraud risk.

### Low Risk Indicators
- Account older than 12 months
- Verified email address
- Verified phone number
- Verified payment method
- Previous successful purchases with no disputes

### Medium Risk Indicators
- Account created within the last 90 days
- Account age between 30 and 90 days
- Limited purchase history
- First refund request
- Email not verified
- Phone number not verified
- Payment method not verified

### High Risk Indicators
- Account created within the last 30 days
- Multiple refund requests in a short period

### Critical Risk Indicators
- Customer account previously suspended
- Customer under fraud investigation
- Multiple linked customer accounts
- Identity verification failure

## Refund Behaviour Analysis

Refund history is a significant indicator of potential abuse.

### Low Risk
- 0–2 approved refunds within the last 12 months

### Medium Risk
- 3 approved refunds within the last 12 months

### High Risk
- More than 3 approved refunds within the last 12 months
- More than 5 return requests within the last 90 days
- Repeated refunds for the same product category
- Repeated refunds near the end of the return window

### Critical Risk
- More than 10 refund requests within 12 months
- Refunds exceeding 70% of total lifetime purchases

## Chargeback Behaviour

Customers with payment disputes require additional scrutiny.

- One previous chargeback → Medium risk
- Two chargebacks → High risk
- Three or more chargebacks → Critical risk
- Chargeback filed after refund already issued → Critical risk

## Purchase Pattern Analysis

The fraud engine should analyse customer purchasing behaviour.

Indicators include:
- Large number of expensive purchases in a short period
- Multiple identical products ordered
- High-value electronics purchased immediately before refund requests
- Bulk purchasing followed by multiple returns
- Significant increase in purchasing activity compared to customer history
- Purchasing only expensive electronics followed by return requests

Unusual purchase patterns increase fraud risk.

## Product Return Behaviour

Repeated returns of similar products may indicate refund abuse.

Examples include:
- Returning every clothing purchase
- Frequently returning opened electronics
- Returning heavily used products as unused
- Returning products shortly before the return window expires
- Repeatedly claiming manufacturer defects without evidence
- Returning identical products multiple times

Repeated behaviour should increase the customer's fraud score.

## Product Image Verification

Where product images are supplied, automated verification may be performed.

The following discrepancies increase fraud risk:
- Uploaded product differs from purchased SKU → High risk
- Brand mismatch → High risk
- Model mismatch → High risk
- Colour mismatch → Medium risk
- Visible serial number differs from purchase records → Critical risk
- Missing required product components visible in image → Medium risk
- Product appears heavily damaged despite unused claim → High risk
- Stock or internet images submitted instead of actual product photographs
- Same image submitted for multiple refund requests → Critical risk
- AI confidence below verification threshold (e.g. below 80%) → Manual review

## Identity Verification

Identity verification should consider:
- Email verification status
- Phone verification status
- Payment method ownership
- Shipping address consistency
- Billing address consistency
- Customer name does not match payment method → Medium risk
- Multiple identities linked to same payment method → High risk

Failure to verify customer identity requires manual investigation.

## Device & Network Risk

The fraud engine may evaluate device and network signals.

Indicators include:
- VPN or proxy usage → Medium risk
- High-risk IP address → Medium risk
- Multiple customer accounts using the same IP address → High risk
- Multiple customer accounts using the same device fingerprint → High risk
- Multiple customer accounts sharing identical payment methods → Critical risk
- Rapid account creation from the same network

These indicators increase fraud risk but do not independently prove fraudulent intent.

## Communication Analysis

Customer communications may be evaluated for inconsistencies.

Examples include:
- Contradictory explanations across multiple refund requests → Medium risk
- Different reasons provided through different support channels → Medium risk
- Claims inconsistent with uploaded evidence → High risk
- Repeated requests after previous final decisions → High risk
- Duplicate refund request for the same order → Critical risk
- Excessive attempts to reopen previously closed refund cases → High risk

Such inconsistencies increase the overall fraud score.

## Fraud Score Adjustments

Certain events increase customer fraud score cumulatively.

| Event | Score Increase |
| --- | --- |
| Account younger than 30 days | +10 |
| More than 3 refunds in 12 months | +20 |
| More than 5 return requests in 90 days | +15 |
| One chargeback | +15 |
| Two chargebacks | +30 |
| Identity verification failed | +25 |
| Product image mismatch | +20 |
| Serial number mismatch | +30 |
| Duplicate refund request | +20 |
| Multiple linked accounts | +25 |
| Customer under fraud investigation | +30 |
| Customer fraud flag set | +35 |

Fraud scores should be cumulative and capped at 100.

## Fraud Engine Decisions

The fraud engine should return one of the following decisions.

### LOW_RISK
No significant fraud indicators detected. Continue automated refund processing where refund policy allows.

### MEDIUM_RISK
Minor fraud indicators detected. Request additional evidence or customer verification before continuing.

### HIGH_RISK
Multiple fraud indicators detected. Forward to manual fraud review. Automatic approval should not occur.

### CRITICAL_RISK
Strong indicators of potential refund abuse or fraudulent activity. Suspend automatic processing and escalate to the Fraud Investigation Team.

## Relationship to Refund Policy

The Anti-Fraud Engine and Refund Policy Engine work together but serve different purposes.

The Refund Policy Engine determines whether the product and request satisfy the published return and refund rules. The Anti-Fraud Engine determines whether the customer's behaviour indicates elevated fraud risk.

A refund may satisfy the Refund Policy but still require manual review if the Anti-Fraud Engine assigns a High or Critical Risk level.
