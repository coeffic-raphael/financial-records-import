"""Extraction schema and confidence aggregation."""

import json

from app.providers.schema import (
    EXTRACTION_FIELDS,
    EXTRACTION_PROMPT,
    ExtractedField,
    ExtractedRecord,
    ExtractionEnvelope,
    flatten,
    json_schema,
    record_confidence,
)


class TestSchemaIsStructuralOnly:
    def test_an_empty_record_parses(self):
        """Every field optional: requiredness is the domain's job, not the schema's.

        This is what lets an incomplete extraction produce a NEEDS_REVIEW record
        instead of failing to parse.
        """
        envelope = ExtractionEnvelope.model_validate({"records": [{}]})
        assert len(envelope.records) == 1

    def test_a_missing_records_key_yields_an_empty_list(self):
        assert ExtractionEnvelope.model_validate({}).records == []

    def test_the_schema_covers_every_business_field(self):
        properties = ExtractedRecord.model_json_schema()["$defs"]
        assert set(ExtractedRecord.model_fields) == set(EXTRACTION_FIELDS)
        assert "ExtractedField" in properties

    def test_the_json_schema_is_serialisable(self):
        """It is sent over the wire, so it must survive json.dumps."""
        assert json.loads(json.dumps(json_schema()))["type"] == "object"


class TestFlatten:
    def test_splits_values_from_confidence(self):
        envelope = ExtractionEnvelope(
            records=[
                ExtractedRecord(
                    reference=ExtractedField(value="INV-1", confidence=0.9),
                    gross_amount=ExtractedField(value="100.00", confidence=0.4),
                )
            ]
        )
        records, confidence = flatten(envelope)

        assert records[0]["reference"] == "INV-1"
        assert records[0]["description"] is None
        assert confidence[0]["reference"] == 0.9
        assert confidence[0]["gross_amount"] == 0.4


class TestRecordConfidence:
    def test_uses_the_minimum_not_the_mean(self):
        """A record is only as trustworthy as its least certain required field.

        A mean would drown one doubtful value among fourteen certain ones and
        let through as VALID a record a human should have read.
        """
        scores = dict.fromkeys(EXTRACTION_FIELDS, 1.0)
        scores["counterparty_name"] = 0.2

        assert record_confidence(scores) == 0.2

    def test_ignores_optional_fields(self):
        scores = dict.fromkeys(EXTRACTION_FIELDS, 1.0)
        scores["invoice_number"] = 0.1  # optional per the data dictionary
        assert record_confidence(scores) == 1.0

    def test_no_scores_means_no_confidence(self):
        assert record_confidence({}) == 0.0


class TestPrompt:
    def test_states_the_balance_trap(self):
        """The statement's Balance column is the mistake most likely to be made."""
        assert "running Balance column    -> IGNORE it entirely" in EXTRACTION_PROMPT

    def test_separates_the_account_holder_from_the_counterparty(self):
        """The header names the account owner, which is the one party that can
        never be the counterparty. Filling it in would turn every statement row
        VALID -- counterparty_name and country are the only fields blocking
        them -- while carrying the wrong name."""
        assert "describes the ACCOUNT, not the counterparty" in EXTRACTION_PROMPT
        assert "so X is never it" in EXTRACTION_PROMPT

    def test_allows_the_header_to_supply_currency_and_country(self):
        """The propagation that IS correct.

        `country` is deliberately included and `counterparty_name` is not. The
        data dictionary names the first `country` and defines it as "ISO alpha-2
        country code" without saying whose; the second carries the counterparty
        prefix and the meaning that comes with it."""
        assert "the currency, when the rows do not" in EXTRACTION_PROMPT
        assert "country, from the account's own IBAN" in EXTRACTION_PROMPT
        assert "not `counterparty_country`" in EXTRACTION_PROMPT

    def test_forbids_guessing_the_amount_breakdown_on_a_statement(self):
        """Observed drift: the same statement row came back with gross null on
        one call and gross = net on another. The second is a guess -- it asserts
        there was no tax -- and it removes a blocker, so a row that named its
        counterparty would go VALID on an invented breakdown."""
        assert "are NULL on a statement row unless" in EXTRACTION_PROMPT
        assert "writing gross = net asserts there was no tax" in EXTRACTION_PROMPT

    def test_forbids_merging_rows_and_cells(self):
        """Observed failure: eight statement rows collapsed into one record,
        with two date cells concatenated into a single field."""
        assert "NEVER merge two rows" in EXTRACTION_PROMPT
        assert "NEVER put two cells in one field" in EXTRACTION_PROMPT

    def test_forbids_inventing_values(self):
        assert "NEVER invent a value" in EXTRACTION_PROMPT

    def test_lists_the_supported_categories(self):
        assert "EXPENSE_REIMBURSEMENT" in EXTRACTION_PROMPT
        assert "FX_ADJUSTMENT" in EXTRACTION_PROMPT
