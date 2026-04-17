import json
from pathlib import Path


def test_molar_weights_exists_and_valid() -> None:
    file_path = Path(__file__).parent.parent.parent.parent / "data" / "ucum" / "molar_weights.json"
    assert file_path.exists(), f"molar_weights.json should exist at {file_path}"

    with open(file_path) as f:
        data = json.load(f)

    assert "glucose" in data
    assert isinstance(data["glucose"], float)
