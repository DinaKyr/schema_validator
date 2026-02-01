#!/usr/bin/env bash
set -euo pipefail

python3 << 'PY'
import json
import re
from pathlib import Path
from collections import Counter

INPUT = Path("/workdir/data/validation_request.json")
OUTPUT = Path("/workdir/validation_results.json")

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

def main():
    if not INPUT.exists():
        raise FileNotFoundError("Input file not found")

    data = json.loads(INPUT.read_text())
    schemas_list = data.get("schemas", [])
    schemas = {s["schema_id"]: s["schema"] for s in schemas_list}
    documents = data.get("documents", [])

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

    OUTPUT.write_text(json.dumps({
        "validation_results": results,
        "summary": summary
    }, indent=2))

if __name__ == "__main__":
    main()
PY
