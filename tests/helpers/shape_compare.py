"""
Response shape comparison utility for mock conformance testing.

Compares field names and types between mock and real API responses
to catch mock drift.
"""


def extract_fields(response, prefix=''):
    """
    Extract field names and their types from a response object.

    Handles both dict responses and objects with attributes.
    Returns a dict of {field_path: type_name}.
    """
    fields = {}

    if isinstance(response, dict):
        for key, value in response.items():
            field_path = f"{prefix}.{key}" if prefix else key
            fields[field_path] = type(value).__name__
            if isinstance(value, dict):
                fields.update(extract_fields(value, field_path))
            elif isinstance(value, list) and value:
                fields.update(extract_fields(value[0], f"{field_path}[]"))
    elif hasattr(response, '__dict__'):
        for key, value in vars(response).items():
            if key.startswith('_'):
                continue
            field_path = f"{prefix}.{key}" if prefix else key
            fields[field_path] = type(value).__name__
            if isinstance(value, dict):
                fields.update(extract_fields(value, field_path))
            elif isinstance(value, list) and value:
                fields.update(extract_fields(value[0], f"{field_path}[]"))

    return fields


def get_top_level_fields(response):
    """
    Get just the top-level field names from a response.

    Returns a set of field names.
    """
    if isinstance(response, dict):
        return set(response.keys())
    elif hasattr(response, '__dict__'):
        return {k for k in vars(response).keys() if not k.startswith('_')}
    return set()


def assert_response_shape_matches(mock_response, real_response, method_name, check_nested=True):
    """
    Assert mock response has all fields present in real response.

    Args:
        mock_response: Response from MockCoinbaseAPI
        real_response: Response from real API
        method_name: API method name for error messages
        check_nested: If True, recurse into nested dicts/lists

    Raises:
        AssertionError if mock is missing fields that real API returns
    """
    if check_nested:
        mock_fields = extract_fields(mock_response)
        real_fields = extract_fields(real_response)
    else:
        mock_fields = {k: '' for k in get_top_level_fields(mock_response)}
        real_fields = {k: '' for k in get_top_level_fields(real_response)}

    missing_fields = set(real_fields.keys()) - set(mock_fields.keys())

    if missing_fields:
        assert not missing_fields, (
            f"{method_name}: mock missing fields present in real API:\n"
            f"  Missing: {sorted(missing_fields)}\n"
            f"  Mock fields: {sorted(mock_fields.keys())}\n"
            f"  Real fields: {sorted(real_fields.keys())}"
        )


def assert_field_types_match(mock_response, real_response, method_name):
    """
    Assert that field types match between mock and real responses.

    Only checks fields that exist in both responses.
    Treats int/float as compatible numeric types.
    """
    mock_fields = extract_fields(mock_response)
    real_fields = extract_fields(real_response)

    common_fields = set(mock_fields.keys()) & set(real_fields.keys())
    type_mismatches = {}

    numeric_types = {'int', 'float'}

    for field in common_fields:
        mock_type = mock_fields[field]
        real_type = real_fields[field]

        if mock_type == real_type:
            continue
        if {mock_type, real_type} <= numeric_types:
            continue

        type_mismatches[field] = (mock_type, real_type)

    if type_mismatches:
        mismatch_details = "\n".join(
            f"  {field}: mock={m}, real={r}"
            for field, (m, r) in sorted(type_mismatches.items())
        )
        assert not type_mismatches, (
            f"{method_name}: field type mismatches:\n{mismatch_details}"
        )
