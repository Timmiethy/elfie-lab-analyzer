def read_modify():
    with open("tests/unit/test_vlm_gateway.py") as f:
        data = f.read()
    data = data.replace('"raw_analyte_label": "Cholesterol",', '"analyte_name": "Cholesterol",')
    data = data.replace('"raw_value_string": "200",', '"value": "200",')
    data = data.replace('"raw_unit_string": "mg/dL",', '"unit": "mg/dL",')
    data = data.replace('"raw_reference_range": "< 200",', '"reference_range_raw": "< 200",')
    with open("tests/unit/test_vlm_gateway.py", "w") as f:
        f.write(data)


read_modify()
