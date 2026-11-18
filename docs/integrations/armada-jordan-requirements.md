# Armada Group — Jordan System Integration Requirements

| | |
|---|---|
| **Source** | Email "JORDAN SYSTEM INTEGRATION" from Ilyas Mohammed (Armada Group), 18 Nov 2026 |
| **Counterparty** | Armada Group (armadagroupco.com) |
| **Purpose** | Armada uses the data for sales analysis, replenishment and order recommendation |
| **Status** | Requirements received — Phase 1 (master file) not started |

> **Credentials:** Armada supplied a Google Cloud service-account JSON key and
> a bucket name by email. Neither is stored in this repository. Keep them in
> the deployment secrets store and inject them through environment variables
> (see [Configuration](#configuration)).

The integration has three data flows, delivered in phases. Phase 2 and 3 do
not start until Armada has reviewed and approved Phase 1.

1. **Master file** — Armada → us (inbound)
2. **Sales data** — us → Armada (outbound)
3. **Return data** — us → Armada (outbound)

---

## Phase 1 — Product master file (inbound)

### Delivery

- Source: Armada's Google Cloud Storage bucket, read with the supplied
  service-account key.
- Format: JSON.
- Frequency: a new file **every day**.
- File name: `ARMADA_MASTER_YYYYMMDD.json`
  (sample provided: `Armada_master_20260816.json`).
- Column definitions: `Armada_Product_Master_Column_Definitions.docx`
  (email attachment). A sample export, `ftp_Armada_master_20261118073003.xlsx`,
  was also attached.

### Product identity

The **SKU Code** is the unique product identifier and must be used to match
products in every later transaction record.

```
Department Code + Product Code      = Style Code
Style Code + Colour Code + Size Code = SKU Code
```

Example: `211105-26006-006-MED`

| Part | Value |
|---|---|
| Department/Product (Style) | `211105-26006` |
| Colour Code | `006` |
| Size | `MED` |
| SKU Code | `211105-26006-006-MED` |

One style has many variants by colour and size.

### Required data model

Each JSON record carries all product attributes, but it must **not** be stored
as one flat product table. Normalise it into separate masters, at minimum:

- Style Master
- Colour Master
- Size Master
- Brand Master
- Sub Brand Master
- Season Master
- Sub Season Master
- Theme Master
- Group Master
- Sub Group Master

The SKU/Product Master links to each of these. Example: every SKU in season
`AW26` references the `AW26` row in the Season Master, so operations such as
"apply 20% discount to all AW26 products" or "sales by brand / theme / group"
work from the relationships.

### Product images

Image data is shared in **binary format** and must be processed as part of
master ingestion.

### Acceptance

Process the sample file, then show Armada how the data was structured. Armada
confirms the mapping and master relationships before transaction data begins.

---

## Phase 2 — Sales data (outbound)

One JSON file per sale date: `JRDSALE_dd-MM-yyyy.json`
(e.g. `JRDSALE_09-09-2026.json`). Field names must match **exactly**.

| Field | Description |
|---|---|
| `Location_code` | Store/location code where the sale was made |
| `Country_code` | Always `JOR` for Jordan |
| `Sale_Year` | Year of the actual sale date, e.g. `2026` |
| `Sale_No` | Unique sale/invoice/transaction number |
| `Sale_Date` | Actual sale date, `dd-MM-yyyy` |
| `Sale_Time` | Actual sale time, `HH:mm` (24-hour) |
| `Customer_code` | Customer ID; `0` if no registered customer |
| `Salesman_code` | ID of the salesperson who processed the sale |
| `Itemcode` | SKU of the item sold |
| `Qty` | Quantity sold (numeric) |
| `Unit_price` | Unit selling price before discount and tax |
| `Unit_disc` | Discount amount per unit |
| `unit_tax` | Tax amount per unit |
| `Gross_Amt` | Line gross amount before discount and tax |
| `Disc_Amt` | Total line discount amount |
| `Disc_Percent` | Line discount percentage |
| `Net_Amt` | Final line amount after discount and tax |
| `Amt_Received` | Total amount received from the customer |
| `By_Cash` | Amount paid in cash |
| `By_Card` | Amount paid by card |
| `Card_Name` | Card type/provider, where applicable |
| `Remarks` | Free-text remarks |
| `Created_on` | Date/time the record was created in our system |
| `Sales_Taxpercent` | Total tax percentage applied to the invoice |
| `Sales_taxAmt` | Total tax amount applied to the invoice |
| `Sales_Type` | `0` = offline, `1` = online |

> Field-name casing is inconsistent in Armada's spec (`unit_tax`,
> `Sales_taxAmt`). Emit them exactly as written above.

---

## Phase 3 — Return data (outbound)

One JSON file per return date: `JRDRETURN_dd-MM-yyyy.json`
(e.g. `JRDRETURN_09-09-2026.json`). Field names must match **exactly**.

| Field | Description |
|---|---|
| `Location_code` | Store/location code where the return was processed |
| `Country_code` | Always `JOR` |
| `Ret_Year` | Year of the actual return date |
| `Ret_No` | Unique return/transaction number |
| `Ret_Date` | Actual return date, `dd-MM-yyyy` |
| `Ret_Time` | Actual return time, `HH:mm` (24-hour) |
| `Customer_code` | Customer ID |
| `Salesman_code` | ID of the salesperson who processed the return |
| `Itemcode` | SKU of the returned item |
| `Qty` | Quantity returned (numeric) |
| `Unit_price` | Unit return amount before tax and discount |
| `Unit_Discount` | Discount amount per unit |
| `Unit_tax` | Tax amount per unit |
| `Gross_Amt` | Line gross amount before discount and tax |
| `Disc_Amt` | Total line discount amount |
| `Disc_Percent` | Line discount percentage |
| `Net_Amt` | Final net return amount after discount and tax |
| `Amt_Returned` | Total amount refunded to the customer |
| `By_Cash` | Amount refunded in cash |
| `By_Card` | Amount refunded by card |
| `Card_Name` | Card type/provider used for the refund |
| `Remarks` | Free-text remarks |
| `Created_on` | Date/time the record was created in our system |
| `Invoice_Ref` | Original sales invoice number the return relates to |
| `Ret_Taxpercent` | Tax percentage of the return transaction |
| `Ret_TaxAmt` | Total tax amount of the return transaction |
| `Return_Type` | `0` = offline, `1` = online |

---

## Rules for outbound files

- Sales and returns are **always separate files**.
- The date in the file name is the actual transaction date, `dd-MM-yyyy`.
- **Send an empty JSON file on days with no transactions**, so Armada can tell
  "no transactions" apart from "file not received".
- Payment/refund fields hold the actual amount processed per method.
- `Invoice_Ref` is mandatory on returns to link back to the original sale.

---

## Configuration

Planned environment variables (names to be confirmed during implementation):

| Variable | Purpose |
|---|---|
| `ARMADA_GCS_BUCKET` | Armada's bucket name (from the email; not committed) |
| `ARMADA_GCS_CREDENTIALS_FILE` | Path to the mounted service-account JSON key |

---

## Open questions for Armada

- Outbound delivery channel for sales/return files (same bucket, another
  bucket, SFTP?) and the upload time each day.
- Whether `Customer_code = 0` also applies to returns with no registered
  customer.
- Exact structure and encoding of the binary image data.
- Whether daily master files are full snapshots or deltas.

## Contacts

- Ilyas Mohammed — Armada Group (sender)
- Nour Eddin — integration owner on our side
