path = "tests/integration/test_phase_14_operational_runtime.py"
with open(path) as f:
    code = f.read()

code = code.replace(
    "    assert retry_response.status_code == 200, retry_response.text\n    retry_payload = retry_response.json()",
    """    assert retry_response.status_code == 200, retry_response.text
    retry_payload = retry_response.json()
    print("RETRY PAYLOAD:", retry_payload)""",
)

with open(path, "w") as f:
    f.write(code)
