import json
import re
from pathlib import Path
from collections import Counter

from apex_arena._types import GradingResult


DATA_FILE_TESTS = Path("/tests/validation_request.json")
DATA_FILE_WORKDIR = Path("/workdir/data/validation_request.json")
OUTPUT_FILE = Path("/workdir/validation_results.json")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

def error(path, message, constraint, expected, actual):
    return {
        "path": path,
        "message": message,
        "constraint": constraint,
        "expected": expected,
        "actual": actual,
    }

def validate_value(value, schema, path, errors):
    t = schema.get("type")

    if t == "string":
        if not isinstance(value, str):
            errors.append(error(path, "Type mismatch", "type", "string", type(value).__name__))
            return
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(error(path, "String too short", "minimum", schema["minLength"], len(value)))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(error(path, "String too long", "maximum", schema["maxLength"], len(value)))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(error(path, "Pattern mismatch", "pattern", schema["pattern"], value))
        if "format" in schema:
            fmt = schema["format"]
            ok = (
                (fmt == "email" and EMAIL_RE.match(value)) or
                (fmt == "uuid" and UUID_RE.match(value)) or
                (fmt == "date" and DATE_RE.match(value)) or
                (fmt == "uri" and URI_RE.match(value))
            )
            if not ok:
                errors.append(error(path, "Invalid format", "format", fmt, value))

    elif t == "number" or t == "integer":
        if not isinstance(value, (int, float)):
            errors.append(error(path, "Type mismatch", "type", t, type(value).__name__))
            return
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(error(path, "Number too small", "minimum", schema["minimum"], value))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(error(path, "Number too large", "maximum", schema["maximum"], value))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(error(path, "Exclusive minimum violated", "minimum", f">{schema['exclusiveMinimum']}", value))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(error(path, "Exclusive maximum violated", "maximum", f"<{schema['exclusiveMaximum']}", value))
        if "multipleOf" in schema and value % schema["multipleOf"] != 0:
            errors.append(error(path, "Not a multiple", "multipleOf", schema["multipleOf"], value))

    elif t == "boolean":
        if not isinstance(value, bool):
            errors.append(error(path, "Type mismatch", "type", "boolean", type(value).__name__))
            return

    elif t == "null":
        if value is not None:
            errors.append(error(path, "Type mismatch", "type", "null", type(value).__name__))
            return

    elif t == "array":
        if not isinstance(value, list):
            errors.append(error(path, "Type mismatch", "type", "array", type(value).__name__))
            return
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(error(path, "Array too short", "minimum", schema["minItems"], len(value)))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(error(path, "Array too long", "maximum", schema["maxItems"], len(value)))
        if schema.get("uniqueItems") and len(value) != len(set(map(str, value))):
            errors.append(error(path, "Duplicate items", "uniqueItems", True, value))
        if "items" in schema:
            for i, item in enumerate(value):
                validate_value(item, schema["items"], f"{path}[{i}]", errors)

    elif t == "object":
        if not isinstance(value, dict):
            errors.append(error(path, "Type mismatch", "type", "object", type(value).__name__))
            return
        props = schema.get("properties", {})
        req = schema.get("required", [])
        for r in req:
            if r not in value:
                errors.append(error(f"{path}.{r}", "Missing required property", "required", True, None))
        if not schema.get("additionalProperties", True):
            for k in value:
                if k not in props:
                    errors.append(error(f"{path}.{k}", "Additional property not allowed", "additionalProperties", False, k))
        for k, v in value.items():
            if k in props:
                validate_value(v, props[k], f"{path}.{k}", errors)

    if "enum" in schema and value not in schema["enum"]:
        errors.append(error(path, "Enum value not allowed", "enum", schema["enum"], value))

def compute_ground_truth(input_data):
    """Compute ground truth validation results from input data."""
    schemas_list = input_data.get("schemas", [])
    schemas = {s["schema_id"]: s["schema"] for s in schemas_list}
    documents = input_data.get("documents", [])

    results = []
    constraint_counter = Counter()

    for doc in documents:
        sid = doc["schema_id"]
        if sid not in schemas:
            errs = [error("$", "Schema not defined", "schema", sid, None)]
        else:
            errs = []
            validate_value(doc["data"], schemas[sid], "$", errs)

        for e in errs:
            constraint_counter[e["constraint"]] += 1

        results.append({
            "document_id": doc["document_id"],
            "schema_id": sid,
            "valid": not errs,
            "errors": errs
        })

    summary = {
        "total_documents": len(results),
        "valid_documents": sum(r["valid"] for r in results),
        "invalid_documents": sum(not r["valid"] for r in results),
        "total_errors": sum(constraint_counter.values()),
        "errors_by_constraint": dict(constraint_counter)
    }

    return {
        "validation_results": results,
        "summary": summary
    }

def grade(_: str) -> GradingResult:
    # Load input
    for p in [DATA_FILE_TESTS, DATA_FILE_WORKDIR]:
        if p.exists():
            input_data = json.loads(p.read_text())
            break
    else:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, "Input file not found")

    if not OUTPUT_FILE.exists():
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, "Missing output file")

    try:
        agent_output = json.loads(OUTPUT_FILE.read_text())
    except Exception as e:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, f"Invalid JSON in output: {str(e)}")

    required_keys = {"validation_results", "summary"}
    if not required_keys.issubset(agent_output):
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, "Missing required top-level fields (validation_results, summary)")

    # Compute ground truth using same logic as solution.sh
    try:
        ground_truth = compute_ground_truth(input_data)
    except Exception as e:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, f"Error computing ground truth: {str(e)}")

    # Compare agent output with ground truth
    agent_results = agent_output.get("validation_results", [])
    agent_summary = agent_output.get("summary", {})
    gt_results = ground_truth["validation_results"]
    gt_summary = ground_truth["summary"]

    #summary stats
    if agent_summary.get("total_documents") != gt_summary["total_documents"]:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Incorrect total_documents: expected {gt_summary['total_documents']}, got {agent_summary.get('total_documents')}")

    if agent_summary.get("valid_documents") != gt_summary["valid_documents"]:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Incorrect valid_documents: expected {gt_summary['valid_documents']}, got {agent_summary.get('valid_documents')}")

    if agent_summary.get("invalid_documents") != gt_summary["invalid_documents"]:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Incorrect invalid_documents: expected {gt_summary['invalid_documents']}, got {agent_summary.get('invalid_documents')}")

    if agent_summary.get("total_errors") != gt_summary["total_errors"]:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Incorrect total_errors: expected {gt_summary['total_errors']}, got {agent_summary.get('total_errors')}")

    if agent_summary.get("errors_by_constraint") != gt_summary["errors_by_constraint"]:
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Constraint error counts mismatch: expected {gt_summary['errors_by_constraint']}, got {agent_summary.get('errors_by_constraint')}")

    # Check individual validation results

    if len(agent_results) != len(gt_results):
        return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                           f"Result count mismatch: expected {len(gt_results)}, got {len(agent_results)}")

    #document id order matters
    for i, (agent_res, gt_res) in enumerate(zip(agent_results, gt_results)):
        if agent_res.get("document_id") != gt_res.get("document_id"):
            return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                               f"Document ID mismatch at index {i}: expected {gt_res.get('document_id')}, got {agent_res.get('document_id')}")

        if agent_res.get("schema_id") != gt_res.get("schema_id"):
            return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                               f"Schema ID mismatch for document {agent_res.get('document_id')}")

        if agent_res.get("valid") != gt_res.get("valid"):
            return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                               f"Validity mismatch for document {agent_res.get('document_id')}: expected {gt_res.get('valid')}, got {agent_res.get('valid')}")

        agent_errors = agent_res.get("errors", [])
        gt_errors = gt_res.get("errors", [])

        if len(agent_errors) != len(gt_errors):
            return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                               f"Error count mismatch for document {agent_res.get('document_id')}: expected {len(gt_errors)}, got {len(agent_errors)}")

        for j, (agent_err, gt_err) in enumerate(zip(agent_errors, gt_errors)):
            if agent_err != gt_err:
                return GradingResult(0.0, {"validation": 0.0}, {"validation": 1.0}, 
                                   f"Error mismatch for document {agent_res.get('document_id')}, error {j}: expected {gt_err}, got {agent_err}")

    return GradingResult(
        score=1.0,
        subscores={"validation": 1.0},
        weights={"validation": 1.0},
        feedback="All validations correct"
    )
