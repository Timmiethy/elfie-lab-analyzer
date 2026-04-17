with open("pyproject.toml", encoding="utf-8") as f:
    text = f.read()

# Add magic-pdf and pdf-inspector
replacement = """    "openai>=1.30.0",
    "magic-pdf[full]>=0.7.1",
    "pdf-inspector>=0.1.0",
"""
text = text.replace('    "openai>=1.30.0",\n', replacement)

with open("pyproject.toml", "w", encoding="utf-8") as f:
    f.write(text)
