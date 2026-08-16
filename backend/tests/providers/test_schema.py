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
        assert "NEVER take the running Balance" in EXTRACTION_PROMPT

    def test_forbids_inventing_values(self):
        assert "NEVER invent a value" in EXTRACTION_PROMPT

    def test_lists_the_supported_categories(self):
        assert "EXPENSE_REIMBURSEMENT" in EXTRACTION_PROMPT
        assert "FX_ADJUSTMENT" in EXTRACTION_PROMPT
